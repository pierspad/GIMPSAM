#!/usr/bin/env python3
"""
GIMPSAM installer — a small guided wizard that sets up the Segment
Anything plug-in for GIMP end to end. It detects GIMP, the plug-in, the
Python backend and your hardware on its own, and only ever asks you to
confirm rather than hunt for folders yourself.

Run it locally (from a GIMPSAM checkout):
    python3 installer.py

Run it ephemerally (nothing is left on disk afterwards — see README.md
for the exact one-liners): pass --ephemeral, which makes the installer
delete itself (and any temp files it downloaded) when it closes.

Every log line is printed to this terminal as it happens, so you can
read the full history or copy it — the GUI itself only ever shows the
current status line, to stay out of the way.
"""

from __future__ import annotations

import glob
import math
import os
import platform
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from tkinter import filedialog, ttk

try:
    from PIL import Image, ImageDraw, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False
    # Every icon is designed against the anti-aliased Pillow path; without
    # it they fall back to plain Tk Canvas primitives (no anti-aliasing,
    # no rounded corners) and look noticeably rougher. Pillow stays an
    # optional import so the installer has zero hard dependencies to even
    # launch, but it's worth telling the user why things look plainer.
    print(
        "Note: Pillow isn't installed for this Python — icons will use a plainer, "
        "non-anti-aliased fallback. Run 'pip install pillow' and relaunch for the crisper look.",
        flush=True,
    )

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isdir(HERE):
        HERE = None
except NameError:
    HERE = None

GITHUB_RAW_BASE = "https://raw.githubusercontent.com/pierspad/GIMPSAM/main/"
PLUGIN_SOURCE_FILES = ["seganyplugin.py", "seganybridge.py"]
_temp_download_dir = None


def resolve_plugin_sources(log=print) -> dict:
    global _temp_download_dir
    if HERE:
        local = {f: os.path.join(HERE, f) for f in PLUGIN_SOURCE_FILES}
        if all(os.path.isfile(p) for p in local.values()):
            return local
    import urllib.request

    if _temp_download_dir is None:
        _temp_download_dir = tempfile.mkdtemp(prefix="gimpsam-installer-")
    result = {}
    for fname in PLUGIN_SOURCE_FILES:
        dest = os.path.join(_temp_download_dir, fname)
        if not os.path.isfile(dest):
            log(f"Fetching {fname} from GitHub (no local checkout found)")
            urllib.request.urlretrieve(GITHUB_RAW_BASE + fname, dest)
        result[fname] = dest
    return result


def cleanup_temp_download_dir():
    global _temp_download_dir
    if _temp_download_dir and os.path.isdir(_temp_download_dir):
        shutil.rmtree(_temp_download_dir, ignore_errors=True)
    _temp_download_dir = None


def self_destruct_if_ephemeral():
    ephemeral = "--ephemeral" in sys.argv or os.environ.get("GIMPSAM_INSTALLER_EPHEMERAL") == "1"
    if ephemeral:
        try:
            path = os.path.abspath(__file__)
            if os.path.isfile(path):
                os.remove(path)
        except (NameError, OSError):
            pass
    cleanup_temp_download_dir()


BACKEND_DIR = os.path.expanduser("~/.local/share/lazygimp/segany")
VENV_DIR = os.path.join(BACKEND_DIR, "venv")
MODELS_DIR = os.path.join(BACKEND_DIR, "models")
VENV_PYTHON = os.path.join(VENV_DIR, "bin", "python3")

# --- dark theme palette -----------------------------------------------------
BG = "#1b1d21"
BG_SIDEBAR = "#1a1c20"
SIDEBAR_HOVER = "#26292f"
CARD_BG = "#26282e"
CARD_BORDER = "#35373e"
TEXT = "#e7e8ea"
TEXT_MUTED = "#9a9da4"
ACCENT = "#4dc3f0"
ACCENT_HOVER = "#6fd0f5"
ACCENT_TEXT = "#08222b"
SUCCESS = "#3fbf7f"
SUCCESS_HOVER = "#57cf93"
DANGER = "#ee5a5f"
DANGER_HOVER = "#f27478"
WARNING = "#f2a93c"
DISABLED_BG = "#34363c"
DISABLED_TEXT = "#6d7076"

TORCH_INDEX_URLS = {
    "CPU (universal, smaller download)": "https://download.pytorch.org/whl/cpu",
    "NVIDIA CUDA 12.6": "https://download.pytorch.org/whl/cu126",
    "NVIDIA CUDA 12.8": "https://download.pytorch.org/whl/cu128",
    "AMD ROCm 6.2": "https://download.pytorch.org/whl/rocm6.2",
}

SAM1_PIP_SPEC = "git+https://github.com/facebookresearch/segment-anything.git"
SAM2_PIP_SPEC = "git+https://github.com/facebookresearch/segment-anything-2.git"
SAM3_HF_PAGE = "https://huggingface.co/facebook/sam3.1"
SAM3_HF_REPO_ID = "facebook/sam3.1"

# Both installers (this one, and LazyGimp's lazygimp.py, which imports this
# module purely as a library — see its resolve_gimpsam_installer()) download
# SAM3 the same way: a one-liner run inside the backend's own venv, because
# huggingface_hub is a dependency of THAT interpreter, not necessarily of
# whatever Python is running the installer GUI itself. Shared here so the
# error-message classification can never drift between the two call sites.
def build_sam3_download_script(dest: str, token: str) -> str:
    return (
        "import sys\n"
        "from huggingface_hub import snapshot_download\n"
        "try:\n"
        f"    snapshot_download(repo_id={SAM3_HF_REPO_ID!r}, local_dir={dest!r}, token={token!r})\n"
        f"    print('SAM3 checkpoint downloaded to', {dest!r})\n"
        "except Exception as e:\n"
        "    msg = str(e)\n"
        "    low = msg.lower()\n"
        "    if '403' in msg or 'gated' in low or 'access to public gated repositories' in low:\n"
        "        print('ERROR-GATED: ' + msg.splitlines()[0])\n"
        "    elif '401' in msg or ('invalid' in low and 'token' in low) or 'unauthorized' in low:\n"
        "        print('ERROR-AUTH: ' + msg.splitlines()[0])\n"
        "    elif 'connect' in low or 'timed out' in low or 'name resolution' in low or 'network' in low:\n"
        "        print('ERROR-NETWORK: ' + msg.splitlines()[0])\n"
        "    else:\n"
        "        print('ERROR-OTHER: ' + msg.splitlines()[0])\n"
        "    sys.exit(1)\n"
    )


def classify_sam3_failure(lines: list[str]) -> str | None:
    """Pull the ERROR-* classification tag build_sam3_download_script()
    prints out of the captured output, if present."""
    for line in reversed(lines):
        if line.startswith("ERROR-"):
            return line
    return None


SAM3_FAILURE_MESSAGES = {
    "ERROR-GATED": (
        "Access denied — your Hugging Face account hasn't been approved for {repo} yet. "
        "Request access at {page}, wait for the approval email, then try again with the same token."
    ),
    "ERROR-AUTH": (
        "The token was rejected (invalid or expired). Generate a fresh read-access token at "
        "huggingface.co/settings/tokens and paste it in again."
    ),
    "ERROR-NETWORK": (
        "Couldn't reach Hugging Face — check your internet connection (and any proxy/firewall), "
        "then try again. This is a several-GB download, so a flaky connection is a common cause."
    ),
}


def sam3_failure_message(tag: str | None) -> str:
    if tag is None:
        return (
            "Couldn't download the SAM3 checkpoint — see the log above for the exact error. "
            "Double-check the token and your access request, then try again."
        )
    kind = tag.split(":", 1)[0].strip()
    detail = tag.split(":", 1)[1].strip() if ":" in tag else ""
    template = SAM3_FAILURE_MESSAGES.get(kind)
    if template is None:
        return f"Couldn't download the SAM3 checkpoint: {detail or tag}"
    base = template.format(repo=SAM3_HF_REPO_ID, page=SAM3_HF_PAGE)
    return f"{base}\n\nDetails: {detail}" if detail else base


@dataclass
class ModelSpec:
    key: str
    family: str  # "SAM1", "SAM2", "SAM3"
    label: str
    size: str
    quality: int  # 1-5
    speed: int  # 1-5
    filename: str | None = None  # None for SAM3 (a folder, not a file)
    url: str | None = None  # None for SAM3 (gated, downloaded via token)


MODEL_REGISTRY: list[ModelSpec] = [
    ModelSpec("sam_vit_b", "SAM1", "vit_b", "375 MB", quality=2, speed=5,
              filename="sam_vit_b_01ec64.pth",
              url="https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth"),
    ModelSpec("sam_vit_l", "SAM1", "vit_l", "1.2 GB", quality=3, speed=3,
              filename="sam_vit_l_0b3195.pth",
              url="https://dl.fbaipublicfiles.com/segment_anything/sam_vit_l_0b3195.pth"),
    ModelSpec("sam_vit_h", "SAM1", "vit_h", "2.5 GB", quality=4, speed=1,
              filename="sam_vit_h_4b8939.pth",
              url="https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth"),
    ModelSpec("sam2_hiera_tiny", "SAM2", "hiera_tiny", "150 MB", quality=2, speed=5,
              filename="sam2_hiera_tiny.pt",
              url="https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_tiny.pt"),
    ModelSpec("sam2_hiera_small", "SAM2", "hiera_small", "180 MB", quality=3, speed=4,
              filename="sam2_hiera_small.pt",
              url="https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_small.pt"),
    ModelSpec("sam2_hiera_base_plus", "SAM2", "hiera_base_plus", "320 MB", quality=4, speed=3,
              filename="sam2_hiera_base_plus.pt",
              url="https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_base_plus.pt"),
    ModelSpec("sam2_hiera_large", "SAM2", "hiera_large", "900 MB", quality=5, speed=2,
              filename="sam2_hiera_large.pt",
              url="https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_large.pt"),
    ModelSpec("sam3", "SAM3", "sam3.1", "~3.4 GB", quality=5, speed=1),
]


def model_path(spec: ModelSpec) -> str:
    if spec.family == "SAM3":
        return os.path.join(MODELS_DIR, "sam3")
    return os.path.join(MODELS_DIR, spec.filename)


def model_installed(spec: ModelSpec) -> bool:
    p = model_path(spec)
    if spec.family == "SAM3":
        # A snapshot_download() that dies partway through (e.g. the 403 a
        # gated/unapproved HF repo returns) can still leave a few small
        # metadata files on disk before it fails — checking "the folder is
        # non-empty" then wrongly reports the model as installed, which
        # hides the failure and disables the Install button on next visit.
        # config.json is one of the last files HF writes for a model repo,
        # so its presence is a much better signal that the snapshot is
        # actually complete.
        return os.path.isdir(p) and os.path.isfile(os.path.join(p, "config.json"))
    return os.path.isfile(p)


def recommended_model_key(hw: "Hardware") -> str:
    # SAM2 is a straight upgrade over SAM1 at comparable size (better
    # accuracy, faster to run), so it's the default across the board now —
    # only the exact checkpoint scales with what the hardware can handle.
    return "sam2_hiera_base_plus" if (hw.gpu and hw.gpu.get("driver_ready")) else "sam2_hiera_small"


def anything_installed(app: "InstallerApp") -> bool:
    if plugin_install_status(app.plugins_dir)[0]:
        return True
    if os.path.isdir(BACKEND_DIR):
        return True
    return any(model_installed(m) for m in MODEL_REGISTRY)


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

@dataclass
class Hardware:
    cpu_cores: int
    python_version: str
    gpu: dict | None


def detect_gpu() -> dict | None:
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            line = next((l for l in out.stdout.splitlines() if l.strip()), None)
            if line:
                return {"vendor": "NVIDIA", "name": line.strip(), "driver_ready": True}
        except Exception:
            pass
    if shutil.which("rocminfo"):
        try:
            out = subprocess.run(["rocminfo"], capture_output=True, text=True, timeout=5)
            name = next(
                (l.split(":", 1)[1].strip() for l in out.stdout.splitlines() if "Marketing Name" in l),
                None,
            )
            return {"vendor": "AMD (ROCm)", "name": name or "AMD GPU", "driver_ready": True}
        except Exception:
            pass
    if shutil.which("lspci"):
        try:
            out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5)
            for line in out.stdout.splitlines():
                low = line.lower()
                if "vga" in low or "3d controller" in low:
                    desc = line.split(":", 2)[-1].strip()
                    if "nvidia" in low:
                        return {"vendor": "NVIDIA", "name": desc, "driver_ready": False}
                    if "amd" in low or "advanced micro devices" in low or "radeon" in low:
                        return {"vendor": "AMD", "name": desc, "driver_ready": False}
        except Exception:
            pass
    return None


def detect_hardware() -> Hardware:
    return Hardware(cpu_cores=os.cpu_count() or 1, python_version=platform.python_version(), gpu=detect_gpu())


def find_gimp_binary() -> str | None:
    return shutil.which("gimp") or shutil.which("gimp-3.0") or shutil.which("gimp-2.10")


def gimp_config_dirs() -> list[str]:
    base = os.path.expanduser("~/.config/GIMP")
    if not os.path.isdir(base):
        return []
    dirs = [d for d in glob.glob(os.path.join(base, "*")) if os.path.isdir(d)]

    def version_key(path):
        parts = []
        for chunk in os.path.basename(path).split("."):
            try:
                parts.append(int(chunk))
            except ValueError:
                parts.append(0)
        return parts

    dirs.sort(key=version_key, reverse=True)
    return dirs


def find_plugins_dir() -> str | None:
    for d in gimp_config_dirs():
        return os.path.join(d, "plug-ins")
    return None


def plugin_install_status(plugins_dir: str | None) -> tuple[bool, str | None]:
    if not plugins_dir:
        return False, None
    dest = os.path.join(plugins_dir, "seganyplugin", "seganyplugin.py")
    return os.path.isfile(dest), dest


def invalidate_gimp_plugin_cache(log=print) -> None:
    """GIMP only re-queries a plug-in's procedures when it thinks something
    changed; that decision is driven by a cache file (pluginrc) sitting next
    to the plug-ins folder, one per config dir. It is usually kept in sync
    correctly, but if a previous run of this installer left the plug-in
    half-installed, or GIMP was left running in the background across an
    "update", the menu entry can end up missing (or stuck showing the old
    version) even after a restart. Deleting pluginrc is always safe — GIMP
    regenerates it from scratch, at the cost of one slightly slower next
    startup — so do it every time we (re)install the plug-in, rather than
    trying to guess whether this particular run actually needs it."""
    for d in gimp_config_dirs():
        pluginrc = os.path.join(d, "pluginrc")
        if os.path.isfile(pluginrc):
            try:
                os.remove(pluginrc)
                log(f"Cleared {pluginrc} so GIMP rescans plug-ins on next launch")
            except OSError as e:
                log(f"Could not clear {pluginrc}: {e} (not fatal)")


def venv_status() -> bool:
    return os.path.isfile(VENV_PYTHON) and os.access(VENV_PYTHON, os.X_OK)


def backend_ready() -> bool:
    """venv_status() only checks that the venv shell exists. That's not the
    same as working: a previous install attempt can fail partway through
    (e.g. a network error reaching download.pytorch.org) and leave a venv
    that exists but has no PyTorch in it. This actually imports it."""
    if not venv_status():
        return False
    try:
        r = subprocess.run([VENV_PYTHON, "-c", "import torch"], capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def choose_directory_native(title: str, start_dir: str | None) -> str | None:
    start_dir = start_dir or os.path.expanduser("~")
    if shutil.which("kdialog"):
        try:
            out = subprocess.run(
                ["kdialog", "--title", title, "--getexistingdirectory", start_dir],
                capture_output=True, text=True, timeout=180,
            )
            return out.stdout.strip() or None
        except Exception:
            pass
    if shutil.which("zenity"):
        try:
            out = subprocess.run(
                ["zenity", "--file-selection", "--directory", "--title", title, f"--filename={start_dir}/"],
                capture_output=True, text=True, timeout=180,
            )
            return out.stdout.strip() or None
        except Exception:
            pass
    return filedialog.askdirectory(title=title, initialdir=start_dir) or None


# --------------------------------------------------------------------------
# Background job runner — every line is printed to the real terminal
# immediately (so you can scroll back or copy the full history there);
# the GUI itself only ever shows the latest single status line.
# --------------------------------------------------------------------------

class Job:
    def __init__(self, log_queue: "queue.Queue[str]"):
        self.log_queue = log_queue
        # Shared with whatever this job is currently running, so a Cancel
        # button on the main thread has something to signal without reaching
        # into subprocess internals itself: cancel() sets the event (which
        # download()'s own poll loop already honours) and, if a subprocess is
        # in flight, terminates it — terminating it is also what unblocks the
        # readline() loop in run_cmd() below, since a dead process closes its
        # stdout pipe and readline() returns "" instead of hanging forever.
        self.cancel_event = threading.Event()
        self.proc: "subprocess.Popen | None" = None

    def cancel(self):
        self.cancel_event.set()
        if self.proc is not None:
            try:
                self.proc.terminate()
            except Exception:
                pass

    def log(self, msg: str):
        print(msg, flush=True)
        self.log_queue.put(msg)

    def run_cmd(self, cmd: list[str], **kw) -> int:
        if self.cancel_event.is_set():
            self.log("Cancelled — skipping: " + " ".join(cmd))
            return -1
        self.log("$ " + " ".join(cmd))
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, **kw)
        for line in iter(self.proc.stdout.readline, ""):
            if line:
                self.log(line.rstrip("\n"))
        self.proc.wait()
        rc = self.proc.returncode
        self.proc = None
        return rc

    def run_cmd_capture(self, cmd: list[str], **kw) -> tuple[int, list[str]]:
        """Same as run_cmd(), but also hands back every printed line — for
        callers that need to tell apart *why* a subprocess failed (e.g. a
        Hugging Face gated-repo 403 vs. an invalid token vs. a plain network
        error) instead of just its exit code."""
        if self.cancel_event.is_set():
            self.log("Cancelled — skipping: " + " ".join(cmd))
            return -1, []
        self.log("$ " + " ".join(cmd))
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, **kw)
        lines: list[str] = []
        for line in iter(self.proc.stdout.readline, ""):
            if line:
                clean = line.rstrip("\n")
                self.log(clean)
                lines.append(clean)
        self.proc.wait()
        rc = self.proc.returncode
        self.proc = None
        return rc, lines

    def download(self, url: str, dest: str, cancel_event: threading.Event | None = None, progress_cb=None) -> bool:
        import urllib.request

        os.makedirs(os.path.dirname(dest), exist_ok=True)
        part = dest + ".part"
        self.log(f"Downloading {url}")
        try:
            with urllib.request.urlopen(url) as resp, open(part, "wb") as out:
                total = int(resp.headers.get("Content-Length", 0))
                read = 0
                last_pct = -1
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        self.log("Cancelled.")
                        return False
                    buf = resp.read(1024 * 256)
                    if not buf:
                        break
                    out.write(buf)
                    read += len(buf)
                    if progress_cb:
                        progress_cb(read, total)
                    if total:
                        pct = int(read * 100 / total)
                        if pct != last_pct and pct % 5 == 0:
                            self.log(f"  {pct}%  ({read // (1024*1024)} MB / {total // (1024*1024)} MB)")
                            last_pct = pct
            os.replace(part, dest)
            self.log(f"Saved to {dest}")
            return True
        finally:
            if os.path.exists(part):
                try:
                    os.remove(part)
                except OSError:
                    pass


# --------------------------------------------------------------------------
# Small monochrome vector icons. Each icon's geometry is defined exactly
# once in _paint_icon() against a tiny backend-agnostic _Painter, which can
# target either a Tk Canvas (no anti-aliasing — Tk just doesn't do it) or a
# Pillow ImageDraw surface rendered at 4x and downsampled with LANCZOS
# (genuinely anti-aliased). render_icon_photo() is what everything should
# call in practice: it prefers the crisp Pillow path and silently falls
# back to raw Canvas primitives if Pillow isn't installed, since this
# installer otherwise has zero hard dependencies to even launch.
# --------------------------------------------------------------------------

class _Painter:
    def __init__(self, target, pil=False):
        self.target = target
        self.pil = pil

    def line(self, pts, color, width=2):
        if self.pil:
            self.target.line(pts, fill=color, width=max(1, round(width)), joint="curve")
        else:
            self.target.create_line(*pts, fill=color, width=width, capstyle="round", joinstyle="round")

    def polygon(self, pts, color=None, outline=None, width=2):
        if self.pil:
            if color is not None:
                self.target.polygon(pts, fill=color)
            if outline is not None:
                self.target.polygon(pts, outline=outline, width=max(1, round(width)))
        else:
            self.target.create_polygon(*pts, fill=color or "", outline=outline or "", width=width)

    def rect(self, x1, y1, x2, y2, color=None, outline=None, width=2, radius=0):
        if self.pil:
            if radius > 0:
                self.target.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=color, outline=outline,
                                               width=max(1, round(width)))
            else:
                self.target.rectangle([x1, y1, x2, y2], fill=color, outline=outline, width=max(1, round(width)))
        else:
            # Plain corners in the Canvas fallback — Tk has no built-in
            # rounded-rect primitive and this path only runs when Pillow
            # isn't installed at all, so it's fine for it to be plainer.
            self.target.create_rectangle(x1, y1, x2, y2, fill=color or "", outline=outline or "", width=width)

    def oval(self, x1, y1, x2, y2, color=None, outline=None, width=2):
        if self.pil:
            self.target.ellipse([x1, y1, x2, y2], fill=color, outline=outline, width=max(1, round(width)))
        else:
            self.target.create_oval(x1, y1, x2, y2, fill=color or "", outline=outline or "", width=width)

    def arc(self, x1, y1, x2, y2, start, extent, color, width=2):
        if self.pil:
            # Tk measures arc angles counter-clockwise from 3 o'clock; PIL
            # measures clockwise. Flipping the sign keeps the same sweep.
            self.target.arc([x1, y1, x2, y2], start=-(start + extent), end=-start, fill=color, width=max(1, round(width)))
        else:
            self.target.create_arc(x1, y1, x2, y2, start=start, extent=extent, style="arc", outline=color, width=width)


def _paint_icon(p: _Painter, cx, cy, kind, color, s, frame=0):
    # A stroke width that scales with the icon's own size rather than a
    # fixed pixel count — at 14px a flat "2px" line reads as too heavy,
    # at 24px it reads as wispy. Every outline/line below goes through
    # this instead of a hardcoded width.
    w = max(1.6, s * 0.16)

    if kind == "home":
        # One pentagon (roof apex + two eaves + two floor corners) instead
        # of a separate roof triangle and body rect — those two used to be
        # drawn at different widths, which is what made it read as an
        # arrow with a stray rectangle rather than a house.
        half = s * 0.85
        top = cy - s * 0.75
        eave = cy - s * 0.05
        bottom = cy + s * 0.85
        p.polygon([cx, top, cx + half, eave, cx + half, bottom, cx - half, bottom, cx - half, eave], color)
    elif kind == "plug":
        p.rect(cx - s * 0.55, cy - s * 0.15, cx + s * 0.55, cy + s * 0.85, outline=color, width=w, radius=s * 0.22)
        p.line([cx - s * 0.28, cy - s * 0.85, cx - s * 0.28, cy - s * 0.15], color, width=w)
        p.line([cx + s * 0.28, cy - s * 0.85, cx + s * 0.28, cy - s * 0.15], color, width=w)
    elif kind == "monitor":
        p.rect(cx - s, cy - s * 0.7, cx + s, cy + s * 0.35, outline=color, width=w, radius=s * 0.14)
        p.line([cx - s * 0.4, cy + s, cx + s * 0.4, cy + s], color, width=w)
        p.line([cx, cy + s * 0.35, cx, cy + s], color, width=w)
    elif kind == "box":
        p.rect(cx - s, cy - s * 0.55, cx + s, cy + s, outline=color, width=w, radius=s * 0.12)
        p.line([cx - s, cy - s * 0.05, cx + s, cy - s * 0.05], color, width=w)  # lid seam
        p.line([cx, cy - s * 0.55, cx, cy + s], color, width=w)  # front tape line
        p.line([cx - s * 0.35, cy - s * 0.55, cx, cy - s * 0.3, cx + s * 0.35, cy - s * 0.55], color, width=w)
    elif kind == "gear":
        outer_r, inner_r = s, s * 0.6
        tooth_half = s * 0.42
        for i in range(8):
            ang = math.radians(i * 45)
            ca, sa = math.cos(ang), math.sin(ang)
            corners = []
            for rr, tt in ((inner_r, -tooth_half), (outer_r, -tooth_half), (outer_r, tooth_half), (inner_r, tooth_half)):
                corners += [cx + rr * ca - tt * sa, cy + rr * sa + tt * ca]
            p.polygon(corners, color)
        # An outline (not filled) hub ring — its own interior stays empty,
        # so this doubles as the gear's center hole with no extra work.
        p.oval(cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r, outline=color, width=s * 0.3)
    elif kind == "bolt":
        p.polygon([
            cx + s * 0.15, cy - s, cx - s * 0.65, cy + s * 0.1, cx - s * 0.05, cy + s * 0.1,
            cx - s * 0.15, cy + s, cx + s * 0.65, cy - s * 0.1, cx + s * 0.05, cy - s * 0.1,
        ], color)
    elif kind == "link":
        # Two overlapping rings — the previous version left a gap between
        # them, so it read as two separate eyes rather than a chain link.
        rx, ry, offset = s * 0.55, s * 0.4, s * 0.32
        ring_w = max(2.0, s * 0.24)
        p.oval(cx - offset - rx, cy - ry, cx - offset + rx, cy + ry, outline=color, width=ring_w)
        p.oval(cx + offset - rx, cy - ry, cx + offset + rx, cy + ry, outline=color, width=ring_w)
    elif kind == "trash":
        top, bottom = cy - s * 0.55, cy + s * 0.95
        top_half, bottom_half = s * 0.62, s * 0.5
        p.polygon([cx - top_half, top, cx + top_half, top, cx + bottom_half, bottom, cx - bottom_half, bottom],
                   outline=color, width=w)
        p.line([cx - s * 0.85, top, cx + s * 0.85, top], color, width=w)  # lid overhang
        p.line([cx - s * 0.28, top, cx - s * 0.28, top - s * 0.28], color, width=w)
        p.line([cx + s * 0.28, top, cx + s * 0.28, top - s * 0.28], color, width=w)
        p.line([cx - s * 0.28, top - s * 0.28, cx + s * 0.28, top - s * 0.28], color, width=w)  # handle
        rib_w = max(1.4, s * 0.1)
        for fx in (-0.26, 0, 0.26):
            p.line([cx + fx * s, top + s * 0.2, cx + fx * s * 0.85, bottom - s * 0.12], color, width=rib_w)
    elif kind == "download":
        p.line([cx, cy - s, cx, cy + s * 0.25], color, width=w)
        p.polygon([cx - s * 0.55, cy - s * 0.05, cx + s * 0.55, cy - s * 0.05, cx, cy + s * 0.55], color)
        p.line([cx - s, cy + s, cx + s, cy + s], color, width=w)
    elif kind == "install":
        # An open tray with a checkmark settling into it, rather than a
        # download arrow — visually distinct from the plain "download"
        # glyph while still reading as "something landed here successfully".
        p.line([cx - s, cy + s * 0.15, cx - s, cy + s], color, width=w)
        p.line([cx - s, cy + s, cx + s, cy + s], color, width=w)
        p.line([cx + s, cy + s * 0.15, cx + s, cy + s], color, width=w)
        p.line([cx - s * 0.55, cy - s * 0.15, cx - s * 0.05, cy + s * 0.35, cx + s * 0.7, cy - s * 0.55],
               color, width=max(2.0, s * 0.2))
    elif kind == "folder":
        p.polygon([
            cx - s, cy - s * 0.35, cx - s * 0.32, cy - s * 0.35, cx - s * 0.15, cy - s * 0.15,
            cx + s, cy - s * 0.15, cx + s, cy + s * 0.55, cx - s, cy + s * 0.55,
        ], color)
    elif kind == "undo":
        p.arc(cx - s * 0.8, cy - s * 0.75, cx + s * 0.8, cy + s * 0.75, 200, 250, color, width=w)
        p.polygon([cx - s * 0.9, cy - s * 0.1, cx - s * 0.32, cy - s * 0.52, cx - s * 0.42, cy + s * 0.08], color)
    elif kind == "warn":
        p.polygon([cx, cy - s, cx - s, cy + s * 0.7, cx + s, cy + s * 0.7], outline=color, width=w)
        p.line([cx, cy - s * 0.15, cx, cy + s * 0.28], color, width=w)
        p.oval(cx - 1.4, cy + s * 0.42, cx + 1.4, cy + s * 0.5, color)
    elif kind == "info":
        p.oval(cx - s * 0.85, cy - s * 0.85, cx + s * 0.85, cy + s * 0.85, outline=color, width=w)
        p.line([cx, cy - s * 0.05, cx, cy + s * 0.55], color, width=w)
        p.oval(cx - 1.2, cy - s * 0.55, cx + 1.2, cy - s * 0.3, color)
    elif kind == "check":
        p.line([cx - s * 0.7, cy, cx - s * 0.1, cy + s * 0.6, cx + s * 0.8, cy - s * 0.6], color, width=max(2.0, s * 0.22))
    elif kind == "x":
        w2 = max(1.8, s * 0.2)
        p.line([cx - s * 0.6, cy - s * 0.6, cx + s * 0.6, cy + s * 0.6], color, width=w2)
        p.line([cx - s * 0.6, cy + s * 0.6, cx + s * 0.6, cy - s * 0.6], color, width=w2)
    elif kind == "refresh":
        p.arc(cx - s * 0.8, cy - s * 0.8, cx + s * 0.8, cy + s * 0.8, 30, 260, color, width=w)
        p.polygon([cx + s * 0.55, cy - s * 0.85, cx + s * 0.95, cy - s * 0.35, cx + s * 0.4, cy - s * 0.25], color)
    elif kind == "spinner":
        start = (frame * 30) % 360
        p.arc(cx - s, cy - s, cx + s, cy + s, start, 110, color, width=w)


def draw_icon(canvas, cx, cy, kind, color=TEXT, s=7, frame=0):
    _paint_icon(_Painter(canvas, pil=False), cx, cy, kind, color, s, frame)


_ICON_PHOTO_CACHE: dict = {}


def render_icon_photo(kind, color, size=18, frame=0):
    if not _PIL_OK:
        return None
    key = (kind, color, size, frame)
    cached = _ICON_PHOTO_CACHE.get(key)
    if cached is not None:
        return cached
    big = size * 4
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _paint_icon(_Painter(draw, pil=True), big / 2, big / 2, kind, color, big * 0.36, frame)
    photo = ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))
    _ICON_PHOTO_CACHE[key] = photo
    return photo


def blit_icon(canvas, cx, cy, kind, color=TEXT, size=18, frame=0):
    """Draw an icon onto a Tk canvas, preferring the crisp Pillow-rendered
    version and falling back to plain (jaggier) Canvas vectors."""
    photo = render_icon_photo(kind, color, size, frame)
    if photo is not None:
        canvas.create_image(cx, cy, image=photo)
    else:
        draw_icon(canvas, cx, cy, kind, color=color, s=size * 0.42, frame=frame)


def icon_canvas(parent, kind, color=TEXT, size=18, bg=None):
    c = tk.Canvas(parent, width=size, height=size, highlightthickness=0, bd=0, bg=bg or parent["bg"])
    blit_icon(c, size / 2, size / 2, kind, color=color, size=size)
    return c


# --------------------------------------------------------------------------
# Rounded-corner widgets
# --------------------------------------------------------------------------

def _rounded_points(x1, y1, x2, y2, r):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


def draw_round_rect(canvas, x1, y1, x2, y2, r=16, **kwargs):
    return canvas.create_polygon(_rounded_points(x1, y1, x2, y2, r), smooth=True, **kwargs)


def autowrap_label(parent, text, fg=TEXT_MUTED, bg=None, font=("Sans", 9), justify="left"):
    lbl = tk.Label(parent, text=text, fg=fg, bg=bg or parent["bg"], font=font, justify=justify, anchor="w")

    def _resize(event):
        new_wrap = max(60, event.width - 4)
        if lbl.cget("wraplength") != new_wrap:
            lbl.configure(wraplength=new_wrap)

    lbl.bind("<Configure>", _resize)
    return lbl


def flatten_entry(entry, bg=CARD_BG):
    """ttk::Entry/Combobox still carry the classic Tk keyboard-focus
    highlight ring as a plain widget option, entirely outside ttk::Style —
    left at its default it shows up as 4 light corner pixels around every
    textbox even with the dark theme applied everywhere else."""
    try:
        entry.configure(highlightthickness=0, highlightbackground=bg, highlightcolor=bg)
    except tk.TclError:
        pass


def rating_widget(parent, quality, speed, bg=CARD_BG):
    row = tk.Frame(parent, bg=bg)

    def dots(container, score):
        for i in range(5):
            c = tk.Canvas(container, width=10, height=10, highlightthickness=0, bd=0, bg=bg)
            c.pack(side="left", padx=1)
            color = ACCENT if i < score else CARD_BORDER
            c.create_oval(1, 1, 9, 9, fill=color, outline="")

    tk.Label(row, text="Quality", bg=bg, fg=TEXT_MUTED, font=("Sans", 9)).pack(side="left", padx=(0, 4))
    qf = tk.Frame(row, bg=bg)
    qf.pack(side="left", padx=(0, 16))
    dots(qf, quality)
    tk.Label(row, text="Speed", bg=bg, fg=TEXT_MUTED, font=("Sans", 9)).pack(side="left", padx=(0, 4))
    sf = tk.Frame(row, bg=bg)
    sf.pack(side="left")
    dots(sf, speed)
    return row


class RoundedButton(tk.Canvas):
    _PALETTE = {
        "primary": (ACCENT, ACCENT_HOVER, ACCENT_TEXT),
        "success": (SUCCESS, SUCCESS_HOVER, "#08210f"),
        "danger": (DANGER, DANGER_HOVER, "#2b0b0c"),
        "secondary": (CARD_BORDER, "#3f424a", TEXT),
    }

    def __init__(self, parent, text, command=None, variant="secondary", icon=None,
                 width=None, height=34, radius=13, font=("Sans", 10, "bold"), bg=None, on_blocked=None):
        super().__init__(parent, height=height, width=width or 1, highlightthickness=0, bd=0, bg=bg or parent["bg"])
        self.command = command
        self.on_blocked = on_blocked
        self.variant = variant
        self.icon = icon
        self.radius = radius
        self.text = text
        self.font = font
        self._enabled = True
        self._hover = False
        self._fixed_width = width
        self._loading = False
        self._loading_base = ""
        self._loading_frame = 0
        self._progress_active = False
        self._progress_frac = 0.0
        self._progress_label = ""
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Button-1>", self._on_click)

    def _set_hover(self, hover):
        if self._enabled:
            self._hover = hover
            self._draw()
            self.configure(cursor="hand2" if hover else "")

    def _on_click(self, _event=None):
        if self._enabled:
            if self.command:
                self.command()
        elif self.on_blocked:
            self.on_blocked()

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self._hover = False
        self._draw()

    def set_text(self, text: str):
        self.text = text
        self._draw()

    def set_variant(self, variant: str):
        self.variant = variant
        self._draw()

    def start_loading(self, base_text="Working"):
        if self._loading:
            return
        self._loading = True
        self._loading_base = base_text
        self._loading_frame = 0
        self._enabled = False
        self._animate()

    def stop_loading(self):
        self._loading = False

    def _animate(self):
        if not self._loading or not self.winfo_exists():
            return
        self._loading_frame += 1
        self._draw()
        self.after(100, self._animate)

    # ---- in-button progress bar (used by one-click setup, which has no
    # wizard UI open to show a status line in) -----------------------------

    def start_progress(self, label="Working"):
        self._progress_active = True
        self._progress_frac = 0.0
        self._progress_label = label
        self._enabled = False
        self._draw()

    def update_progress(self, frac: float, label: str | None = None):
        if not self._progress_active:
            return
        self._progress_frac = max(0.0, min(1.0, frac))
        if label is not None:
            self._progress_label = label
        self._draw()

    def stop_progress(self):
        self._progress_active = False
        self._draw()

    def _draw(self):
        self.delete("all")
        w = max(self.winfo_width(), self._fixed_width or 1, 10)
        h = int(self["height"])
        base_fill, hover_fill, fg = self._PALETTE[self.variant]

        if self._progress_active:
            # The bar sweeps left-to-right in the button's own hover shade
            # over its normal fill, so the label stays legible throughout
            # instead of needing a separate track/fill color pair.
            draw_round_rect(self, 1, 1, w - 1, h - 1, self.radius, fill=base_fill, outline="")
            fw = (w - 2) * self._progress_frac
            if fw > 0:
                r = min(self.radius, fw / 2, (h - 2) / 2)
                draw_round_rect(self, 1, 1, 1 + fw, h - 1, r, fill=hover_fill, outline="")
            label = f"{self._progress_label} — {round(self._progress_frac * 100)}%"
            self.create_text(w / 2, h / 2, text=label, fill=fg, font=self.font, anchor="center")
            return

        if not self._enabled and not self._loading:
            fill, fg = DISABLED_BG, DISABLED_TEXT
        elif self._loading:
            fill = base_fill
        elif self._hover:
            fill = hover_fill
        else:
            fill = base_fill
        draw_round_rect(self, 1, 1, w - 1, h - 1, self.radius, fill=fill, outline="")
        if self._loading:
            blit_icon(self, 22, h / 2, "spinner", color=fg, size=16, frame=self._loading_frame % 12)
            self.create_text(38, h / 2, text=self._loading_base + "…", fill=fg, font=self.font, anchor="w")
        elif self.icon:
            blit_icon(self, 22, h / 2, self.icon, color=fg, size=17)
            self.create_text(38, h / 2, text=self.text, fill=fg, font=self.font, anchor="w")
        else:
            self.create_text(w / 2, h / 2, text=self.text, fill=fg, font=self.font, anchor="center")


class RoundedCard(tk.Frame):
    def __init__(self, parent, bg=CARD_BG, border=CARD_BORDER, radius=18, pad=18, width=None, height=None):
        super().__init__(parent, bg=parent["bg"])
        self._bg, self._border, self._radius, self._pad = bg, border, radius, pad
        self._fixed_height = height
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=parent["bg"])
        if width:
            self.canvas.configure(width=width)
        if height:
            self.canvas.configure(height=height)
        self.canvas.pack(fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(pad, pad, window=self.body, anchor="nw")
        self._last_h = None
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.body.bind("<Configure>", self._on_body_configure)

    def _on_canvas_configure(self, event=None):
        w = self.canvas.winfo_width()
        opts = {"width": max(0, w - 2 * self._pad)}
        if self._fixed_height:
            # Stretch the body to fill the whole fixed-height card, not
            # just its own natural content height — otherwise a
            # bottom-anchored child (e.g. a button) lands at a different
            # absolute position in every card whose content height differs.
            opts["height"] = max(0, self._fixed_height - 2 * self._pad)
        self.canvas.itemconfig(self._win, **opts)
        self._redraw(w, self.canvas.winfo_height())

    def _on_body_configure(self, event=None):
        if self._fixed_height:
            h = self._fixed_height
        else:
            h = self.body.winfo_reqheight() + 2 * self._pad
            if h != self._last_h:
                self._last_h = h
                self.canvas.configure(height=h)
        self._redraw(self.canvas.winfo_width(), h)

    def _redraw(self, w, h):
        self.canvas.delete("card_bg")
        if w > 4 and h > 4:
            draw_round_rect(self.canvas, 1, 1, w - 1, h - 1, self._radius,
                             fill=self._bg, outline=self._border, width=1, tags="card_bg")
            self.canvas.tag_lower("card_bg")

    def finalize(self):
        self.update_idletasks()
        self._on_body_configure()
        self._on_canvas_configure()


class ProgressBar(tk.Canvas):
    """A slim rounded progress bar for tracking one download against a
    known total — the spinner tells you *something* is happening, this
    tells you how far along it actually is."""

    def __init__(self, parent, width=200, height=7, bg=None, track=CARD_BORDER, fill=ACCENT):
        super().__init__(parent, width=width, height=height, highlightthickness=0, bd=0, bg=bg or parent["bg"])
        self._frac = 0.0
        self._track, self._fillc = track, fill
        self.bind("<Configure>", lambda e: self._draw())

    def set_fraction(self, frac: float):
        self._frac = max(0.0, min(1.0, frac))
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width() or int(self["width"])
        h = int(self["height"])
        draw_round_rect(self, 0, 0, w, h, h / 2, fill=self._track, outline="")
        fw = w * self._frac
        if fw >= h:
            draw_round_rect(self, 0, 0, fw, h, h / 2, fill=self._fillc, outline="")


class ModernCheckbox(tk.Canvas):
    """A small rounded checkbox drawn to match the rest of the theme —
    ttk.Checkbutton's native box looks jarring next to everything else."""

    def __init__(self, parent, variable: tk.BooleanVar, command=None, size=20, bg=None):
        super().__init__(parent, width=size, height=size, highlightthickness=0, bd=0, bg=bg or parent["bg"])
        self.variable = variable
        self.command = command
        self.size = size
        self._trace_id = variable.trace_add("write", lambda *_a: self._draw())
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._toggle)
        self.bind("<Enter>", lambda e: self.configure(cursor="hand2"))
        self.bind("<Destroy>", self._on_destroy)
        self._draw()

    def _toggle(self, _event=None):
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()

    def _on_destroy(self, _event=None):
        try:
            self.variable.trace_remove("write", self._trace_id)
        except Exception:
            pass

    def _draw(self):
        if not self.winfo_exists():
            return
        self.delete("all")
        s = self.size
        if self.variable.get():
            draw_round_rect(self, 1, 1, s - 1, s - 1, 6, fill=ACCENT, outline="")
            blit_icon(self, s / 2, s / 2, "check", color=ACCENT_TEXT, size=max(10, int(s * 0.75)))
        else:
            draw_round_rect(self, 1.5, 1.5, s - 1.5, s - 1.5, 6, fill="", outline=CARD_BORDER, width=2)


def bind_click_recursive(widget, handler, skip=()):
    """Binds a click handler onto `widget` and every descendant of it
    (used to make a whole card clickable, not just its button), skipping
    any widget in `skip` — namely the button that already has its own
    click handling, so we don't double-fire or clobber its hover state."""
    if widget in skip:
        return
    try:
        widget.configure(cursor="hand2")
    except tk.TclError:
        pass
    widget.bind("<Button-1>", lambda e: handler())
    for child in widget.winfo_children():
        bind_click_recursive(child, handler, skip)


class ScrollableFrame(tk.Frame):
    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="Modern.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y", padx=(4, 0))
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self._win, width=e.width))
        self._wheel_bound_ids: set[int] = set()
        self.bind_mousewheel_recursive()

    def bind_mousewheel_recursive(self, widget=None):
        """<Enter>/<Leave> on the canvas only fire while the pointer is over
        the sliver of it not covered by a child window — and `inner` (plus
        every card, button and label packed inside it) covers essentially
        all of it. That's why the wheel used to only work in the gaps
        between rows. Attach directly to every descendant instead, and
        call this again after adding widgets dynamically (e.g. after
        populating a step) so new children pick it up too."""
        widget = widget or self.inner
        if id(widget) not in self._wheel_bound_ids:
            widget.bind("<MouseWheel>", self._on_wheel, add="+")
            widget.bind("<Button-4>", self._on_up, add="+")
            widget.bind("<Button-5>", self._on_down, add="+")
            self._wheel_bound_ids.add(id(widget))
        for child in widget.winfo_children():
            self.bind_mousewheel_recursive(child)

    def _on_wheel(self, event):
        if self.canvas.winfo_exists():
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _on_up(self, event):
        if self.canvas.winfo_exists():
            self.canvas.yview_scroll(-2, "units")

    def _on_down(self, event):
        if self.canvas.winfo_exists():
            self.canvas.yview_scroll(2, "units")


def themed_dialog(root, title, message, kind="info"):
    win = tk.Toplevel(root)
    win.configure(bg=BG)
    win.title(title)
    win.transient(root)
    win.resizable(False, False)
    card = RoundedCard(win, radius=18, pad=20, width=380)
    card.pack(padx=2, pady=2)
    tk.Label(card.body, text=title, bg=CARD_BG, fg=TEXT, font=("Sans", 13, "bold")).pack(anchor="w")
    autowrap_label(card.body, message, fg=TEXT_MUTED, bg=CARD_BG, font=("Sans", 10)).pack(anchor="w", fill="x", pady=(10, 18))
    result = {"value": None}
    btns = tk.Frame(card.body, bg=CARD_BG)
    btns.pack(anchor="e")

    def close(v):
        result["value"] = v
        win.destroy()

    if kind == "confirm":
        RoundedButton(btns, "Cancel", variant="secondary", width=90, command=lambda: close(False)).pack(side="left", padx=(0, 8))
        RoundedButton(btns, "Confirm", variant="danger", icon="trash", width=120, command=lambda: close(True)).pack(side="left")
    else:
        RoundedButton(btns, "OK", variant="primary", width=90, command=lambda: close(True)).pack(side="left")
    card.finalize()
    win.update_idletasks()
    rx, ry, rw, rh = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
    ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
    win.geometry(f"+{rx + max(0, (rw - ww) // 2)}+{ry + max(0, (rh - wh) // 2)}")
    win.grab_set()
    win.wait_window()
    return result["value"]


def themed_info(root, title, message):
    themed_dialog(root, title, message, kind="info")


def themed_confirm(root, title, message) -> bool:
    return bool(themed_dialog(root, title, message, kind="confirm"))


def show_snackbar(app: "InstallerApp", message: str, tone: str = "warn", duration_ms: int = 2000):
    colors = {"warn": ("#3a2e14", WARNING), "error": ("#3a1414", DANGER), "ok": ("#123522", SUCCESS)}
    bgc, fg = colors.get(tone, colors["warn"])
    root = app.root
    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg=root["bg"])
    card = RoundedCard(win, bg=bgc, border=bgc, radius=14, pad=14)
    card.pack()
    row = tk.Frame(card.body, bg=bgc)
    row.pack()
    icon_canvas(row, "warn" if tone == "warn" else ("x" if tone == "error" else "check"), color=fg, size=16, bg=bgc).pack(side="left", padx=(0, 8))
    tk.Label(row, text=message, bg=bgc, fg=fg, font=("Sans", 10, "bold")).pack(side="left")
    card.finalize()
    win.update_idletasks()
    x = root.winfo_rootx() + max(0, (root.winfo_width() - win.winfo_reqwidth()) // 2)
    y = root.winfo_rooty() + root.winfo_height() - 110
    win.geometry(f"+{x}+{y}")
    win.after(duration_ms, lambda: win.destroy() if win.winfo_exists() else None)


# --------------------------------------------------------------------------
# Download queue
# --------------------------------------------------------------------------

class DownloadManager:
    def __init__(self, app: "InstallerApp"):
        self.app = app
        self.queue: list[str] = []
        self.active_key: str | None = None
        self.cancel_event: threading.Event | None = None
        self.progress: dict = {"done": 0, "total": 0}

    def state_for(self, key: str) -> str:
        if key == self.active_key:
            return "downloading"
        if key in self.queue:
            return "queued"
        return "idle"

    def enqueue(self, spec: ModelSpec):
        if self.active_key is None:
            self._start(spec)
        elif spec.key not in self.queue:
            self.queue.append(spec.key)
        self._notify()

    def dequeue(self, spec: ModelSpec):
        if spec.key in self.queue:
            self.queue.remove(spec.key)
        self._notify()

    def cancel_active(self):
        if self.cancel_event:
            self.cancel_event.set()

    def _start(self, spec: ModelSpec):
        self.active_key = spec.key
        self.cancel_event = threading.Event()
        self.progress = {"done": 0, "total": 0}
        job = Job(self.app.log_queue)
        cancel_event = self.cancel_event

        def progress_cb(done, total):
            self.progress["done"] = done
            self.progress["total"] = total

        def run():
            dest = model_path(spec)
            ok = False
            try:
                if os.path.isfile(dest):
                    job.log(f"{spec.label} already downloaded at {dest}")
                    ok = True
                else:
                    ok = job.download(spec.url, dest, cancel_event, progress_cb=progress_cb)
            except Exception as e:
                job.log(f"ERROR downloading {spec.label}: {e}")
            self.app.root.after(0, lambda: self._finish(spec, ok))

        threading.Thread(target=run, daemon=True).start()
        self._notify()

    def _finish(self, spec, ok):
        self.active_key = None
        self.cancel_event = None
        self._notify()
        if self.queue:
            next_key = self.queue.pop(0)
            next_spec = next(m for m in MODEL_REGISTRY if m.key == next_key)
            self._start(next_spec)

    def _notify(self):
        # Used to call app.refresh_all(), which tears down and rebuilds the
        # whole current step — including a brand-new ScrollableFrame for
        # the Models step, at scroll position 0. That's what made the list
        # jump back to the top on every Install click. Update the existing
        # ModelRow widgets in place instead, so nothing gets destroyed and
        # the scroll position stays exactly where the user left it. If the
        # Models step isn't the one currently on screen there's nothing
        # visible to refresh — it re-derives its state next time it's built.
        app = self.app
        if not getattr(app, "in_wizard", False):
            return
        models_step = getattr(app, "models_step", None)
        if models_step is not None and getattr(app, "current_index", None) == 3:
            models_step.refresh_rows()


# --------------------------------------------------------------------------
# Wizard shell
# --------------------------------------------------------------------------

STEPS = [("home", "Overview"), ("plug", "Plug-in"), ("monitor", "Backend"), ("box", "Models")]


class SidebarItem(tk.Canvas):
    def __init__(self, parent, icon, text, command, width=220, height=46):
        super().__init__(parent, width=width, height=height, highlightthickness=0, bd=0, bg=BG_SIDEBAR)
        self.icon, self.text_, self.command = icon, text, command
        self.active = False
        self.hover = False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Button-1>", lambda e: self.command())

    def _set_hover(self, hover):
        self.hover = hover
        self._draw()
        self.configure(cursor="hand2" if hover else "")

    def set_active(self, active: bool):
        self.active = active
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width() or int(self["width"])
        h = int(self["height"])
        if self.active:
            draw_round_rect(self, 10, 5, w - 10, h - 5, 13, fill=ACCENT, outline="")
            fg = ACCENT_TEXT
        elif self.hover:
            draw_round_rect(self, 10, 5, w - 10, h - 5, 13, fill=SIDEBAR_HOVER, outline="")
            fg = TEXT
        else:
            fg = TEXT
        blit_icon(self, 30, h / 2, self.icon, color=fg, size=17)
        self.create_text(58, h / 2, text=self.text_, fill=fg, font=("Sans", 11, "bold" if self.active else "normal"), anchor="w")


class InstallerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("GIMPSAM installer")
        root.geometry("1060x760")
        root.minsize(920, 660)
        root.configure(bg=BG)

        self._style()

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.busy = False
        self.in_wizard = False
        self.current_job = None
        self.hw = detect_hardware()
        self.plugins_dir = find_plugins_dir()
        self.download_manager = DownloadManager(self)

        self.root_frame = tk.Frame(root, bg=BG)
        self.root_frame.pack(fill="both", expand=True)

        self.show_landing()
        self.root.after(150, self._drain_log_queue)

    def _style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TEntry", fieldbackground="#303237", foreground=TEXT, insertcolor=TEXT,
                         bordercolor="#303237", lightcolor="#303237", darkcolor="#303237",
                         borderwidth=0, relief="flat", padding=6)
        style.configure("TCombobox", fieldbackground="#303237", background="#303237", foreground=TEXT,
                         arrowcolor=TEXT, bordercolor="#303237", lightcolor="#303237", darkcolor="#303237",
                         borderwidth=0, relief="flat", padding=6)
        style.map("TCombobox",
                   fieldbackground=[("readonly", "#303237")],
                   foreground=[("readonly", TEXT)],
                   background=[("readonly", "#303237")])
        style.layout("Modern.Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {"children": [
                ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"}),
            ], "sticky": "ns"}),
        ])
        style.configure("Modern.Vertical.TScrollbar", gripcount=0, background="#4a4d54",
                         troughcolor=BG, bordercolor=BG, lightcolor="#4a4d54", darkcolor="#4a4d54",
                         relief="flat", width=8, arrowsize=0)
        style.configure("TCheckbutton", background=CARD_BG, foreground=TEXT)
        style.map("TCheckbutton", background=[("active", CARD_BG)])
        style.configure("TSeparator", background=CARD_BORDER)
        self.root.option_add("*TCombobox*Listbox.background", "#303237")
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", ACCENT_TEXT)

    # ---- status bar (replaces the old activity-log panel) ---------------

    def _build_status_bar(self, parent):
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x", padx=26, pady=(0, 18), side="bottom")
        self.status_spinner = tk.Canvas(bar, width=16, height=16, highlightthickness=0, bd=0, bg=BG)
        self.status_spinner.pack(side="left", padx=(0, 8))
        self.status_var = tk.StringVar(value="Full log is printed to the terminal this was launched from.")
        tk.Label(bar, textvariable=self.status_var, bg=BG, fg=TEXT_MUTED, font=("Sans", 9), anchor="w").pack(side="left", fill="x", expand=True)
        self._status_spin_frame = 0
        self._status_spinning = False

    def _spin_status(self):
        if not self._status_spinning or not self.status_spinner.winfo_exists():
            return
        self.status_spinner.delete("all")
        blit_icon(self.status_spinner, 8, 8, "spinner", color=ACCENT, size=14, frame=self._status_spin_frame % 12)
        self._status_spin_frame += 1
        self.root.after(90, self._spin_status)

    # ---- landing screen -------------------------------------------------

    def show_landing(self):
        self.in_wizard = False
        for w in self.root_frame.winfo_children():
            w.destroy()

        wrap = tk.Frame(self.root_frame, bg=BG)
        wrap.pack(fill="both", expand=True)
        center = tk.Frame(wrap, bg=BG)
        center.place(relx=0.5, rely=0.42, anchor="center")

        tk.Label(center, text="GIMPSAM", bg=BG, fg=TEXT, font=("Sans", 28, "bold")).pack()
        tk.Label(center, text="Segment Anything for GIMP", bg=BG, fg=TEXT_MUTED, font=("Sans", 11)).pack(pady=(2, 34))

        row = tk.Frame(center, bg=BG)
        row.pack()

        CARD_W, CARD_H = 320, 250

        custom = RoundedCard(row, radius=20, pad=24, width=CARD_W, height=CARD_H)
        custom.grid(row=0, column=0, padx=10)
        title_row = tk.Frame(custom.body, bg=CARD_BG)
        title_row.pack(anchor="w")
        icon_canvas(title_row, "gear", color=TEXT, size=20).pack(side="left", padx=(0, 8))
        tk.Label(title_row, text="Custom install", bg=CARD_BG, fg=TEXT, font=("Sans", 14, "bold")).pack(side="left")
        autowrap_label(
            custom.body, "Step through plug-in, backend and model choices yourself, with full control over each one.",
            bg=CARD_BG, font=("Sans", 9),
        ).pack(anchor="w", fill="x", pady=(8, 16))
        open_btn = RoundedButton(custom.body, "Open", variant="secondary", width=272, height=40, command=self.enter_wizard)
        open_btn.pack(anchor="w", side="bottom")
        custom.finalize()
        bind_click_recursive(custom, self.enter_wizard, skip=(open_btn,))

        auto = RoundedCard(row, radius=20, pad=24, width=CARD_W, height=CARD_H)
        auto.grid(row=0, column=1, padx=10)
        title_row2 = tk.Frame(auto.body, bg=CARD_BG)
        title_row2.pack(anchor="w")
        icon_canvas(title_row2, "bolt", color=TEXT, size=20).pack(side="left", padx=(0, 8))
        tk.Label(title_row2, text="One click setup", bg=CARD_BG, fg=TEXT, font=("Sans", 14, "bold")).pack(side="left")
        autowrap_label(
            auto.body, "Installs the plug-in, the Python backend, and a model recommended for this machine.",
            bg=CARD_BG, font=("Sans", 9),
        ).pack(anchor="w", fill="x", pady=(8, 16))
        # Cancel sits right below Start, created up front but only packed
        # once a run is actually in flight (see start_full_auto_setup) —
        # this way the card's layout never jumps and there is always a
        # concrete widget for that method to reveal.
        self.cancel_btn = RoundedButton(auto.body, "Cancel", variant="danger", icon="x", width=272, height=32,
                                         command=self.cancel_current_job)
        self.start_btn = RoundedButton(auto.body, "Start", variant="primary", width=272, height=40, command=self.start_full_auto_setup)
        self.start_btn.pack(anchor="w", side="bottom")
        auto.finalize()
        bind_click_recursive(auto, self.start_full_auto_setup, skip=(self.start_btn, self.cancel_btn))

        if anything_installed(self):
            btn_row = tk.Frame(center, bg=BG)
            btn_row.pack(pady=(18, 0))
            RoundedButton(btn_row, "Close installer and open GIMP", variant="primary", icon="bolt", width=340,
                          command=self.launch_gimp_and_close).pack(pady=(0, 10))
            RoundedButton(btn_row, "Uninstall GIMPSAM from this system", variant="danger", icon="trash", width=340,
                          command=self.show_uninstall_confirm).pack()

    def launch_gimp_and_close(self):
        gimp_bin = find_gimp_binary()
        if not gimp_bin:
            show_snackbar(self, "GIMP not found on PATH — install it first", tone="error")
            return
        try:
            subprocess.Popen([gimp_bin], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              start_new_session=True)
        except Exception as e:
            show_snackbar(self, f"Couldn't launch GIMP: {e}", tone="error")
            return
        self.root.destroy()

    # ---- uninstall screen -------------------------------------------------

    def show_uninstall_confirm(self):
        self.in_wizard = False
        for w in self.root_frame.winfo_children():
            w.destroy()

        wrap = tk.Frame(self.root_frame, bg=BG)
        wrap.pack(fill="both", expand=True)
        self._build_status_bar(wrap)

        content = tk.Frame(wrap, bg=BG)
        content.pack(fill="both", expand=True, padx=40, pady=30)

        title_row = tk.Frame(content, bg=BG)
        title_row.pack(anchor="w")
        icon_canvas(title_row, "trash", color=DANGER, size=24).pack(side="left", padx=(0, 10))
        tk.Label(title_row, text="Uninstall GIMPSAM", bg=BG, fg=TEXT, font=("Sans", 20, "bold")).pack(side="left")
        tk.Label(content, text="Choose what to remove from this system, or leave everything checked to remove it all.",
                 bg=BG, fg=TEXT_MUTED, font=("Sans", 10)).pack(anchor="w", pady=(4, 18))

        installed, dest = plugin_install_status(self.plugins_dir)
        items = []
        if installed:
            items.append(("plug", "Plug-in files", os.path.dirname(dest)))
        if os.path.isdir(BACKEND_DIR):
            items.append(("monitor", "Python backend (virtualenv + every downloaded model)", BACKEND_DIR))

        # Buttons pinned to the bottom first, so they land at a fixed
        # position regardless of how many items are listed above them.
        btns = tk.Frame(content, bg=BG)
        btns.pack(fill="x", pady=(20, 0), side="bottom")

        card = RoundedCard(content)
        card.pack(fill="both", expand=True)
        check_vars: list[tuple[tk.BooleanVar, str]] = []
        if items:
            for icon, name, path in items:
                row = tk.Frame(card.body, bg=CARD_BG)
                row.pack(fill="x", pady=7, anchor="w")
                var = tk.BooleanVar(value=True)
                ModernCheckbox(row, var, command=lambda: update_confirm_label(), bg=CARD_BG).pack(side="left", padx=(0, 10))
                icon_canvas(row, icon, color=DANGER, size=18, bg=CARD_BG).pack(side="left", padx=(0, 10))
                col = tk.Frame(row, bg=CARD_BG)
                col.pack(side="left", fill="x", expand=True)
                tk.Label(col, text=name, bg=CARD_BG, fg=TEXT, font=("Sans", 10, "bold"), anchor="w").pack(anchor="w")
                autowrap_label(col, path, fg=TEXT_MUTED, bg=CARD_BG, font=("Sans", 9)).pack(anchor="w", fill="x")
                check_vars.append((var, path))
        else:
            tk.Label(card.body, text="Nothing found to remove.", bg=CARD_BG, fg=TEXT_MUTED).pack(anchor="w")
        card.finalize()

        RoundedButton(btns, "Cancel", variant="secondary", width=110, command=self.show_landing).pack(side="left")
        confirm_btn = RoundedButton(btns, "Delete selected", variant="danger", icon="trash", width=200,
                                     command=lambda: self.on_confirm_uninstall([p for v, p in check_vars if v.get()]))
        confirm_btn.pack(side="left", padx=8)
        RoundedButton(btns, "Delete all", variant="danger", icon="trash", width=140,
                      command=lambda: self.on_confirm_uninstall([p for _, p in check_vars])).pack(side="left")

        def update_confirm_label():
            n = sum(1 for v, _ in check_vars if v.get())
            confirm_btn.set_text(f"Delete selected ({n})")
            confirm_btn.set_enabled(n > 0)

        update_confirm_label()

    def on_confirm_uninstall(self, paths_to_delete):
        def task(job: Job):
            for path in paths_to_delete:
                if not os.path.exists(path):
                    job.log(f"Already gone: {path}")
                    continue
                job.log(f"Removing {path}")
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                    if os.path.exists(path):
                        job.log(f"WARNING: {path} still exists after removal attempt (check permissions).")
                    else:
                        job.log(f"Removed {path}")
                except Exception as e:
                    job.log(f"ERROR removing {path}: {e}")
            job.log("Uninstall finished.")

        self.run_in_background(task, on_done=self.show_landing)

    # ---- wizard shell -----------------------------------------------------

    def enter_wizard(self):
        self.in_wizard = True
        for w in self.root_frame.winfo_children():
            w.destroy()

        outer = tk.Frame(self.root_frame, bg=BG)
        outer.pack(fill="both", expand=True)

        sidebar = tk.Frame(outer, bg=BG_SIDEBAR, width=220)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="GIMPSAM", bg=BG_SIDEBAR, fg=TEXT, font=("Sans", 16, "bold")).pack(anchor="w", padx=18, pady=(22, 0))
        tk.Label(sidebar, text="setup wizard", bg=BG_SIDEBAR, fg=TEXT_MUTED, font=("Sans", 9)).pack(anchor="w", padx=18, pady=(0, 18))

        self.step_items = []
        for i, (icon, name) in enumerate(STEPS):
            item = SidebarItem(sidebar, icon, name, command=lambda i=i: self.show_step(i))
            item.pack(fill="x", padx=6, pady=2)
            self.step_items.append(item)

        back_item = SidebarItem(sidebar, "undo", "Start over", command=self.show_landing, height=40)
        back_item.pack(fill="x", side="bottom", padx=6, pady=(0, 14))

        right = tk.Frame(outer, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        self._build_status_bar(right)

        self.content = tk.Frame(right, bg=BG)
        self.content.pack(fill="both", expand=True, padx=26, pady=22)

        self.steps = [OverviewStep(self), PluginStep(self), BackendStep(self), ModelsStep(self)]
        self.show_step(0)

    def show_step(self, index: int):
        self.current_index = index
        for i, item in enumerate(self.step_items):
            item.set_active(i == index)
        for child in self.content.winfo_children():
            child.destroy()
        self.steps[index].build(self.content)

    def refresh_all(self):
        if not self.in_wizard:
            return
        self.hw = detect_hardware()
        self.show_step(self.current_index)

    # Progress tools like pip/tqdm/huggingface_hub rewrite their line in
    # place with '\r' rather than emitting a real newline per update; when
    # captured through a pipe that habit can turn into either one very long
    # literal string, or a flood of separate near-identical lines. A status
    # bar meant to show exactly one line has no size limit by default, so
    # either case ends up stretching (and visibly breaking) the whole
    # window's layout instead of just showing stale-looking text. Clamp and
    # normalize whatever the log queue hands us so that can never happen.
    _STATUS_MAX_CHARS = 160

    def _drain_log_queue(self):
        last = None
        try:
            while True:
                msg = self.log_queue.get_nowait()
                last = msg
        except queue.Empty:
            pass
        if last is not None and hasattr(self, "status_var") and self.status_var is not None:
            clean = " ".join(last.replace("\r", " ").split())
            if len(clean) > self._STATUS_MAX_CHARS:
                clean = "…" + clean[-(self._STATUS_MAX_CHARS - 1):]
            try:
                self.status_var.set(clean)
            except tk.TclError:
                pass
        self.root.after(150, self._drain_log_queue)

    def set_busy(self, busy: bool):
        self.busy = busy
        if not hasattr(self, "status_spinner") or not self.status_spinner.winfo_exists():
            return
        self._status_spinning = busy
        if busy:
            self._spin_status()
        else:
            self.status_spinner.delete("all")

    def run_in_background(self, fn, on_done=None):
        if self.busy:
            themed_info(self.root, "Busy", "Another operation is already running.")
            return
        self.set_busy(True)

        # Stashed on self so a Cancel button elsewhere (built by whoever
        # called run_in_background) can reach this exact run's Job and call
        # .cancel() on it without needing its own separate plumbing.
        job = Job(self.log_queue)
        self.current_job = job

        def wrapper():
            try:
                fn(job)
            except Exception as e:
                job.log(f"ERROR: {e}")
            finally:
                if self.current_job is job:
                    self.current_job = None
                self.root.after(0, lambda: (self.set_busy(False), (on_done() if on_done else self.refresh_all())))

        threading.Thread(target=wrapper, daemon=True).start()

    def cancel_current_job(self):
        """Used by a Cancel button next to a running one-click/custom-install
        progress bar. Terminates whatever subprocess is in flight; the caller
        is responsible for running any cleanup once the job actually stops
        (its on_done callback still fires normally after cancellation)."""
        if self.current_job is not None:
            self.current_job.log("Cancel requested by user — stopping...")
            self.current_job.cancel()

    # ---- one click setup ------------------------------------------------

    def start_full_auto_setup(self):
        # Deliberately does NOT call enter_wizard(): one-click setup is
        # meant to require zero input from the user, so it stays on the
        # landing screen and reports progress as a bar inside the Start
        # button itself. Only Custom install opens the step-by-step UI.
        # Every step is still logged to the real terminal via Job.log,
        # exactly as before.
        if self.busy:
            themed_info(self.root, "Busy", "Setup is already running.")
            return

        # This installer only ever sets up the PLUG-IN — it copies files
        # into an existing GIMP's plug-ins folder, which does not exist
        # without GIMP itself. Running the venv/PyTorch/model steps anyway
        # (as used to happen) just leaves a backend nothing can use yet, so
        # refuse to start at all and say why, instead of silently doing
        # partial, useless work.
        if not find_gimp_binary():
            show_snackbar(self, "GIMP not found — install GIMP first, then run One-Click Setup", tone="warn")
            return

        hw = self.hw
        torch_index = TORCH_INDEX_URLS["CPU (universal, smaller download)"]
        if hw.gpu and hw.gpu.get("driver_ready"):
            if "NVIDIA" in hw.gpu["vendor"]:
                torch_index = TORCH_INDEX_URLS["NVIDIA CUDA 12.8"]
            elif "AMD" in hw.gpu["vendor"]:
                torch_index = TORCH_INDEX_URLS["AMD ROCm 6.2"]
        rec_spec = next(m for m in MODEL_REGISTRY if m.key == recommended_model_key(hw))
        plugins_dir = self.plugins_dir
        outcome = {"ok": True, "reason": None}

        # Rough share of total wall-clock time each phase tends to take —
        # PyTorch and the model checkpoint dominate, so they get most of
        # the bar; the rest exists mainly so the button doesn't look stuck
        # during the quick steps.
        phases = [
            ("Installing plug-in", 0.05),
            ("Creating virtual environment", 0.10),
            ("Installing PyTorch", 0.50),
            ("Installing dependencies", 0.10),
            ("Installing SAM backend", 0.10),
            ("Downloading model", 0.15),
        ]
        phase_start, acc = {}, 0.0
        for name, weight in phases:
            phase_start[name] = acc
            acc += weight
        phase_weight = dict(phases)

        def set_progress(phase_name, sub_frac=0.0):
            frac = phase_start[phase_name] + phase_weight[phase_name] * max(0.0, min(1.0, sub_frac))
            self.root.after(0, lambda: self.start_btn.update_progress(frac, phase_name))

        self.start_btn.start_progress(phases[0][0])
        # Swap Start for Cancel for the duration of this run — re-shown as
        # Start automatically once show_landing() rebuilds the screen in
        # _finish_auto_setup(). _enabled only gates click handling, not the
        # progress-bar drawing, so start_btn keeps animating normally.
        self.start_btn._enabled = False
        self.cancel_btn.pack(anchor="w", pady=(6, 0))

        def cancelled(job) -> bool:
            if job.cancel_event.is_set():
                outcome["ok"] = False
                outcome["cancelled"] = True
                outcome["reason"] = "Cancelled — cleaning up what was installed so far."
                job.log(outcome["reason"])
                return True
            return False

        def task(job: Job):
            set_progress("Installing plug-in")
            if plugins_dir:
                try:
                    sources = resolve_plugin_sources(job.log)
                    dest_dir = os.path.join(plugins_dir, "seganyplugin")
                    job.log(f"Installing plug-in into {dest_dir}")
                    os.makedirs(dest_dir, exist_ok=True)
                    for fname, path in sources.items():
                        shutil.copy2(path, dest_dir)
                        os.chmod(os.path.join(dest_dir, fname), 0o755)
                    invalidate_gimp_plugin_cache(job.log)
                except Exception as e:
                    job.log(f"Could not install plug-in files: {e}")
            else:
                job.log("No GIMP plug-ins folder found — install GIMP first, then use Custom install.")
            if cancelled(job):
                return

            set_progress("Creating virtual environment")
            os.makedirs(BACKEND_DIR, exist_ok=True)
            if not venv_status():
                job.log(f"Creating virtualenv at {VENV_DIR}")
                if job.run_cmd([sys.executable, "-m", "venv", VENV_DIR]) != 0:
                    if cancelled(job):
                        return
                    outcome["ok"] = False
                    outcome["reason"] = "Failed to create the virtualenv."
                    job.log(outcome["reason"])
                    return
            if cancelled(job):
                return
            pip = os.path.join(VENV_DIR, "bin", "pip")
            job.run_cmd([pip, "install", "--upgrade", "pip"])
            if cancelled(job):
                return

            set_progress("Installing PyTorch")
            job.log(f"Installing PyTorch from {torch_index}")
            if job.run_cmd([pip, "install", "torch", "torchvision", "--index-url", torch_index]) != 0:
                if cancelled(job):
                    return
                outcome["ok"] = False
                outcome["reason"] = (
                    "PyTorch failed to install — this is almost always a network problem reaching "
                    "download.pytorch.org rather than a bug in the installer. The plug-in files were "
                    "still installed. Check your connection, then use Custom install → Backend to retry."
                )
                job.log(outcome["reason"])
                return

            set_progress("Installing dependencies")
            job.run_cmd([pip, "install", "numpy", "pillow", "opencv-python-headless"])
            if cancelled(job):
                return

            set_progress("Installing SAM backend")
            if rec_spec.family == "SAM2":
                job.log("Installing SAM2 (segment-anything-2)")
                job.run_cmd([pip, "install", SAM2_PIP_SPEC])
            else:
                job.log("Installing SAM1 (segment-anything)")
                job.run_cmd([pip, "install", SAM1_PIP_SPEC])
            if cancelled(job):
                return

            set_progress("Downloading model")
            dest = model_path(rec_spec)
            if not os.path.isfile(dest):
                job.log(f"Downloading recommended model: {rec_spec.label}")
                job.download(rec_spec.url, dest, cancel_event=job.cancel_event,
                             progress_cb=lambda done, total: set_progress(
                                 "Downloading model", done / total if total else 0.0))
            else:
                job.log(f"{rec_spec.label} already downloaded.")
            if cancelled(job):
                return

            job.log("One click setup complete! Restart GIMP to load the plug-in.")

        def done():
            if outcome["ok"]:
                self.start_btn.update_progress(1.0, "Done")
                self.root.after(700, lambda: self._finish_auto_setup(outcome))
            elif outcome.get("cancelled"):
                self._cleanup_cancelled_setup(outcome)
            else:
                self._finish_auto_setup(outcome)

        self.run_in_background(task, on_done=done)

    def _cleanup_cancelled_setup(self, outcome):
        """Runs right after a cancelled one-click setup: removes whatever it
        managed to create (partial venv/backend, copied plug-in files) so a
        cancel never leaves the system in a half-installed state. Reuses the
        exact same paths the Uninstall screen already knows about."""

        def task(job: Job):
            dest_dir = os.path.join(self.plugins_dir, "seganyplugin") if self.plugins_dir else None
            for path in (dest_dir, BACKEND_DIR):
                if not path or not os.path.exists(path):
                    continue
                job.log(f"Removing {path}")
                try:
                    shutil.rmtree(path)
                    job.log(f"Removed {path}")
                except Exception as e:
                    job.log(f"ERROR removing {path}: {e}")
            job.log("Cleanup finished — the system is back to how it was before Cancel.")

        self.run_in_background(task, on_done=lambda: self._finish_auto_setup(outcome))

    def _finish_auto_setup(self, outcome):
        if self.start_btn.winfo_exists():
            self.start_btn.stop_progress()
        self.show_landing()
        if outcome.get("cancelled"):
            show_snackbar(self, "Setup cancelled — cleaned up, nothing left behind", tone="warn")
        elif not outcome["ok"]:
            themed_info(self.root, "Setup failed", outcome["reason"])


def page_header(parent, title):
    tk.Label(parent, text=title, bg=BG, fg=TEXT, font=("Sans", 18, "bold")).pack(anchor="w", pady=(0, 16))


def nav_row(parent, app, back_to=None, next_to=None, next_label="Continue", next_enabled=True, side="top"):
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", pady=(18, 0), side=side)
    if back_to is not None:
        RoundedButton(row, "← Back", variant="secondary", width=90, command=lambda: app.show_step(back_to)).pack(side="left")
    if next_to is not None:
        btn = RoundedButton(row, f"{next_label} →", variant="primary", width=140, command=lambda: app.show_step(next_to))
        btn.pack(side="left", padx=8)
        btn.set_enabled(next_enabled)
        return btn


def callout(parent, text, tone="info"):
    colors = {"info": ("#16303a", "#7fd0f0"), "warn": ("#3a2e14", WARNING), "ok": ("#123522", SUCCESS)}
    icon_kind = {"info": "info", "warn": "warn", "ok": "check"}[tone]
    bgc, fg = colors[tone]
    card = RoundedCard(parent, bg=bgc, border=bgc, radius=14, pad=12)
    card.pack(fill="x", pady=(4, 12))
    row = tk.Frame(card.body, bg=bgc)
    row.pack(fill="x")
    icon_canvas(row, icon_kind, color=fg, size=18, bg=bgc).pack(side="left", padx=(0, 8), anchor="n")
    autowrap_label(row, text, fg=fg, bg=bgc, font=("Sans", 9)).pack(side="left", fill="x", expand=True)
    card.finalize()
    return card


# --------------------------------------------------------------------------
# Step 1 — Overview
# --------------------------------------------------------------------------

class OverviewStep:
    def __init__(self, app: InstallerApp):
        self.app = app

    def build(self, parent):
        app = self.app
        page_header(parent, "What's on this machine")

        hw = app.hw
        gimp_bin = find_gimp_binary()
        installed, dest = plugin_install_status(app.plugins_dir)
        backend_ok = backend_ready()
        n_installed = sum(1 for m in MODEL_REGISTRY if model_installed(m))

        card = RoundedCard(parent)
        card.pack(fill="x")
        body = card.body

        rows = [
            ("check" if gimp_bin else "warn", "GIMP", f"found at {gimp_bin}" if gimp_bin else "not found on PATH — install GIMP first", SUCCESS if gimp_bin else WARNING),
            ("check" if installed else "x", "Plug-in files", f"installed at {dest}" if installed else "not installed yet", SUCCESS if installed else TEXT_MUTED),
            ("check" if backend_ok else "x", "Python backend", "ready" if backend_ok else ("virtualenv exists but PyTorch isn't importable — a previous install likely failed" if venv_status() else "not set up yet"), SUCCESS if backend_ok else (WARNING if venv_status() else TEXT_MUTED)),
            ("check" if n_installed else "x", "Models downloaded", f"{n_installed} of {len(MODEL_REGISTRY)}", SUCCESS if n_installed else TEXT_MUTED),
        ]
        for icon, name, detail, color in rows:
            row = tk.Frame(body, bg=CARD_BG)
            row.pack(fill="x", pady=8)
            icon_canvas(row, icon, color=color, size=18, bg=CARD_BG).pack(side="left", padx=(0, 10))
            tk.Label(row, text=name, bg=CARD_BG, fg=TEXT, font=("Sans", 11, "bold"), width=18, anchor="w").pack(side="left", padx=(0, 14))
            autowrap_label(row, detail, fg=TEXT_MUTED, bg=CARD_BG, font=("Sans", 10)).pack(side="left", fill="x", expand=True)

        ttk.Separator(body, orient="horizontal").pack(fill="x", pady=10)

        hw_row = tk.Frame(body, bg=CARD_BG)
        hw_row.pack(fill="x")
        icon_canvas(hw_row, "gear", color=ACCENT, size=18, bg=CARD_BG).pack(side="left", padx=(0, 10))
        tk.Label(hw_row, text="Hardware", bg=CARD_BG, fg=TEXT, font=("Sans", 11, "bold"), width=18, anchor="w").pack(side="left", padx=(0, 14))
        gpu_desc = f"{hw.gpu['vendor']} — {hw.gpu['name']}" if hw.gpu else "no dedicated GPU detected"
        if hw.gpu and not hw.gpu.get("driver_ready", True):
            gpu_desc += " (present, drivers not loaded)"
        autowrap_label(
            hw_row, f"{hw.cpu_cores} CPU cores · {gpu_desc} · Python {hw.python_version}",
            fg=TEXT_MUTED, bg=CARD_BG, font=("Sans", 10),
        ).pack(side="left", fill="x", expand=True)

        card.finalize()

        if hw.gpu and hw.gpu.get("driver_ready"):
            callout(parent, "A GPU is available — segmentation runs there automatically, no configuration needed.", "ok")
        else:
            callout(
                parent,
                f"No usable GPU found — segmentation runs on CPU, already configured to use all {hw.cpu_cores} cores.\n"
                "All models will work, but might be very slow.",
                "warn",
            )

        if not gimp_bin:
            callout(parent, "GIMP isn't detected on PATH — Continue is disabled below until it is. "
                             "Install GIMP, then click Re-check.", "warn")

        btns = tk.Frame(parent, bg=BG)
        btns.pack(fill="x", pady=(6, 0))
        RoundedButton(btns, "Re-check", icon="refresh", variant="secondary", width=140, command=app.refresh_all).pack(side="left")
        continue_btn = RoundedButton(btns, "Continue →", variant="primary", width=140, command=lambda: app.show_step(1))
        continue_btn.pack(side="left", padx=8)
        continue_btn.set_enabled(bool(gimp_bin))


# --------------------------------------------------------------------------
# Step 2 — Plug-in files
# --------------------------------------------------------------------------

class PluginStep:
    def __init__(self, app: InstallerApp):
        self.app = app

    def build(self, parent):
        app = self.app
        page_header(parent, "Plug-in files")

        installed, dest = plugin_install_status(app.plugins_dir)

        card = RoundedCard(parent)
        card.pack(fill="x")
        body = card.body

        if installed:
            callout(body, f"Already installed at {dest} — this will update it to the latest version.", "ok")
        else:
            callout(body, "Not installed yet on this system.", "warn")

        tk.Label(body, text="Target folder (auto-detected)", bg=CARD_BG, fg=TEXT, font=("Sans", 10, "bold")).pack(anchor="w", pady=(0, 6))
        row = tk.Frame(body, bg=CARD_BG)
        row.pack(fill="x", pady=(0, 16))
        self.path_var = tk.StringVar(value=app.plugins_dir or "(none found — choose manually)")
        entry = ttk.Entry(row, textvariable=self.path_var, font=("Sans", 10))
        entry.pack(side="left", fill="x", expand=True, ipady=4)
        flatten_entry(entry)
        RoundedButton(row, "Change…", icon="folder", variant="secondary", width=130, command=self.on_change_dir).pack(side="left", padx=(8, 0))

        self.install_btn = RoundedButton(body, "Install / Update Plug-in Files", icon="install", variant="success", width=290, command=self.on_install)
        self.install_btn.pack(anchor="w")

        card.finalize()
        nav_row(parent, app, back_to=0, next_to=2, next_enabled=installed)

    def on_change_dir(self):
        chosen = choose_directory_native("Select your GIMP plug-ins folder", self.app.plugins_dir)
        if chosen:
            self.app.plugins_dir = chosen
            self.app.show_step(1)

    def on_install(self):
        plugins_dir = self.path_var.get().strip()
        if not plugins_dir or not os.path.isdir(os.path.dirname(plugins_dir) or plugins_dir):
            themed_info(self.app.root, "No folder", "Pick a valid GIMP plug-ins folder first.")
            return
        self.app.plugins_dir = plugins_dir
        self.install_btn.start_loading("Installing")

        def task(job: Job):
            try:
                sources = resolve_plugin_sources(job.log)
            except Exception as e:
                job.log(f"ERROR: could not obtain plug-in source files: {e}")
                return
            dest_dir = os.path.join(plugins_dir, "seganyplugin")
            job.log(f"Installing into {dest_dir}")
            os.makedirs(dest_dir, exist_ok=True)
            for fname, path in sources.items():
                shutil.copy2(path, dest_dir)
                os.chmod(os.path.join(dest_dir, fname), 0o755)
            invalidate_gimp_plugin_cache(job.log)
            job.log("Plug-in files installed. Restart GIMP to load the change.")

        self.app.run_in_background(task, on_done=lambda: self.app.show_step(1))


# --------------------------------------------------------------------------
# Step 3 — Python backend
# --------------------------------------------------------------------------

class BackendStep:
    def __init__(self, app: InstallerApp):
        self.app = app

    def build(self, parent):
        app = self.app
        page_header(parent, "Python backend")

        venv_exists = venv_status()
        torch_ok = backend_ready()
        card = RoundedCard(parent)
        card.pack(fill="x")
        body = card.body

        if torch_ok:
            callout(body, f"Ready at {VENV_DIR}", "ok")
        elif venv_exists:
            callout(
                body,
                "A virtualenv exists here, but PyTorch isn't importable inside it — the last install "
                "attempt likely failed partway through (often a network issue reaching "
                "download.pytorch.org). Run Repair Backend below to retry.",
                "warn",
            )
        else:
            callout(body, "Not set up yet.", "warn")

        tk.Label(body, text="PyTorch build", bg=CARD_BG, fg=TEXT, font=("Sans", 10, "bold")).pack(anchor="w", pady=(0, 6))
        default_choice = list(TORCH_INDEX_URLS.keys())[0]
        hw = app.hw
        if hw.gpu and hw.gpu.get("driver_ready"):
            if "NVIDIA" in hw.gpu["vendor"]:
                default_choice = "NVIDIA CUDA 12.8"
            elif "AMD" in hw.gpu["vendor"]:
                default_choice = "AMD ROCm 6.2"
        self.torch_choice = tk.StringVar(value=default_choice)
        torch_combo = ttk.Combobox(body, textvariable=self.torch_choice, values=list(TORCH_INDEX_URLS.keys()),
                                    state="readonly", width=34, font=("Sans", 10))
        torch_combo.pack(anchor="w", pady=(0, 16))
        flatten_entry(torch_combo)

        autowrap_label(
            body,
            "GPU builds parallelize automatically via CUDA/ROCm. The CPU build already uses every core "
            "on this machine for each operation — nothing more to tune there.",
            fg=TEXT_MUTED, bg=CARD_BG, font=("Sans", 9),
        ).pack(anchor="w", fill="x", pady=(0, 16))

        label_text = "Repair Backend" if venv_exists else "Install Backend"
        self.setup_btn = RoundedButton(body, label_text, icon="gear", variant="success", width=260, command=self.on_setup)
        self.setup_btn.pack(anchor="w")

        card.finalize()
        nav_row(parent, app, back_to=1, next_to=3, next_enabled=torch_ok)

    def on_setup(self):
        torch_index = TORCH_INDEX_URLS[self.torch_choice.get()]
        self.setup_btn.start_loading("Installing" if not venv_status() else "Repairing")
        outcome = {"ok": True, "reason": None}

        def task(job: Job):
            os.makedirs(BACKEND_DIR, exist_ok=True)
            if not venv_status():
                job.log(f"Creating virtualenv at {VENV_DIR}")
                if job.run_cmd([sys.executable, "-m", "venv", VENV_DIR]) != 0:
                    outcome["ok"] = False
                    outcome["reason"] = "Failed to create the virtualenv (is python3-venv installed?)."
                    job.log(outcome["reason"])
                    return
            else:
                job.log(f"Reusing existing virtualenv at {VENV_DIR}")

            pip = os.path.join(VENV_DIR, "bin", "pip")
            job.run_cmd([pip, "install", "--upgrade", "pip"])
            job.log(f"Installing PyTorch from {torch_index}")
            if job.run_cmd([pip, "install", "torch", "torchvision", "--index-url", torch_index]) != 0:
                outcome["ok"] = False
                outcome["reason"] = (
                    "PyTorch failed to install. This is almost always a network problem reaching "
                    "download.pytorch.org (no internet access, DNS blocked, or a proxy/firewall in the "
                    "way) rather than a bug in this installer — check your connection and try again."
                )
                job.log(outcome["reason"])
                return
            job.log("Installing image dependencies")
            job.run_cmd([pip, "install", "numpy", "pillow", "opencv-python-headless"])
            job.log("Installing SAM1 backend")
            job.run_cmd([pip, "install", SAM1_PIP_SPEC])
            job.log("Installing SAM2 backend — this can take a few minutes")
            if job.run_cmd([pip, "install", SAM2_PIP_SPEC]) != 0:
                job.log("SAM2 failed to build — SAM1 models will still work. This usually means a "
                        "C/C++ toolchain is missing; install one and re-run this step.")
            job.log("Python backend ready.")

        def done():
            self.app.show_step(2)
            if not outcome["ok"]:
                themed_info(self.app.root, "Backend setup failed", outcome["reason"])

        self.app.run_in_background(task, on_done=done)


# --------------------------------------------------------------------------
# Step 4 — Models
# --------------------------------------------------------------------------

class ModelRow:
    def __init__(self, parent, app: InstallerApp, spec: ModelSpec, recommended: bool = False):
        self.app = app
        self.spec = spec

        self.card = RoundedCard(parent, pad=14, radius=16)
        self.card.pack(fill="x", pady=6)
        body = self.card.body

        top = tk.Frame(body, bg=CARD_BG)
        top.pack(fill="x")

        left = tk.Frame(top, bg=CARD_BG)
        left.pack(side="left", fill="x", expand=True)
        name_row = tk.Frame(left, bg=CARD_BG)
        name_row.pack(anchor="w")
        tk.Label(name_row, text=spec.label, bg=CARD_BG, fg=TEXT, font=("Sans", 12, "bold")).pack(side="left")
        tk.Label(name_row, text=f"   {spec.size}", bg=CARD_BG, fg=TEXT_MUTED, font=("Sans", 9)).pack(side="left")
        if recommended:
            tk.Label(name_row, text="  ★ Recommended", bg=CARD_BG, fg=ACCENT, font=("Sans", 9, "bold")).pack(side="left")
        rating_widget(left, spec.quality, spec.speed, bg=CARD_BG).pack(anchor="w", pady=(4, 0))
        self.status_lbl = tk.Label(left, text="", bg=CARD_BG, fg=SUCCESS, font=("Sans", 9, "bold"))
        self.status_lbl.pack(anchor="w", pady=(4, 0))
        self.progress_row = tk.Frame(left, bg=CARD_BG)
        self.progress_bar = ProgressBar(self.progress_row, width=220, height=7, bg=CARD_BG)
        self.progress_bar.pack(side="left")
        self.progress_lbl = tk.Label(self.progress_row, text="", bg=CARD_BG, fg=TEXT_MUTED, font=("Sans", 8))
        self.progress_lbl.pack(side="left", padx=(8, 0))

        right = tk.Frame(top, bg=CARD_BG)
        right.pack(side="right")
        self.install_btn = RoundedButton(right, "Install", icon="install", variant="success", width=150, command=self.on_install)
        self.install_btn.pack(side="left", padx=(0, 8))
        self.remove_btn = RoundedButton(right, "Remove", icon="trash", variant="danger", width=160, command=self.on_remove)
        self.remove_btn.pack(side="left")

        self.card.finalize()
        self.render()

    def render(self):
        dm = self.app.download_manager
        installed = model_installed(self.spec)
        state = dm.state_for(self.spec.key)
        any_active = dm.active_key is not None

        self.install_btn.stop_loading()
        self.progress_row.pack_forget()
        if installed:
            self.status_lbl.configure(text="Installed")
            self.install_btn.set_text("Install")
            self.install_btn.set_variant("success")
            self.install_btn.set_enabled(False)
            self.remove_btn.set_text("Remove")
            self.remove_btn.set_variant("danger")
            self.remove_btn.set_enabled(True)
        elif state == "downloading":
            self.status_lbl.configure(text="")
            self.install_btn.start_loading("Installing")
            self.remove_btn.set_text("Cancel")
            self.remove_btn.set_variant("danger")
            self.remove_btn.set_enabled(True)
            self.progress_row.pack(anchor="w", pady=(4, 0))
            self._poll_progress()
        elif state == "queued":
            self.status_lbl.configure(text="Queued")
            self.install_btn.set_text("Queued")
            self.install_btn.set_variant("secondary")
            self.install_btn.set_enabled(False)
            self.remove_btn.set_text("Remove from queue")
            self.remove_btn.set_variant("secondary")
            self.remove_btn.set_enabled(True)
        else:
            self.status_lbl.configure(text="")
            self.install_btn.set_text("Add to queue" if any_active else "Install")
            self.install_btn.set_variant("success")
            self.install_btn.set_enabled(True)
            self.remove_btn.set_text("Remove")
            self.remove_btn.set_variant("danger")
            self.remove_btn.set_enabled(False)

    def _poll_progress(self):
        if not self.card.winfo_exists():
            return
        dm = self.app.download_manager
        if dm.state_for(self.spec.key) != "downloading":
            return
        done, total = dm.progress.get("done", 0), dm.progress.get("total", 0)
        if total:
            frac = done / total
            self.progress_bar.set_fraction(frac)
            self.progress_lbl.configure(text=f"{done // (1024*1024)} / {total // (1024*1024)} MB ({int(frac * 100)}%)")
        else:
            self.progress_bar.set_fraction(0)
            self.progress_lbl.configure(text=f"{done // (1024*1024)} MB downloaded")
        self.card.after(300, self._poll_progress)

    def on_install(self):
        if model_installed(self.spec):
            return
        self.app.download_manager.enqueue(self.spec)

    def on_remove(self):
        dm = self.app.download_manager
        state = dm.state_for(self.spec.key)
        if state == "downloading":
            if themed_confirm(self.app.root, "Cancel download", f"Cancel downloading {self.spec.label}?"):
                dm.cancel_active()
        elif state == "queued":
            dm.dequeue(self.spec)
        else:
            dest = model_path(self.spec)
            if not themed_confirm(self.app.root, "Remove model", f"Delete {dest}?"):
                return

            def task(job: Job):
                try:
                    if os.path.isdir(dest):
                        shutil.rmtree(dest)
                    else:
                        os.remove(dest)
                    if os.path.exists(dest):
                        job.log(f"WARNING: {dest} still exists after removal attempt (check permissions).")
                    else:
                        job.log(f"Removed {dest}")
                except Exception as e:
                    job.log(f"ERROR removing {dest}: {e}")

            self.app.run_in_background(task)


class ModelsStep:
    def __init__(self, app: InstallerApp):
        self.app = app

    def build(self, parent):
        app = self.app
        app.models_step = self
        self.rows: list[ModelRow] = []
        page_header(parent, "Models")

        autowrap_label(
            parent,
            "Quality/Speed are rough 1-5 estimates from Meta's own published benchmarks, comparable "
            "within a family — SAM2's hiera_large edges out SAM1's vit_h at actually smaller size, which "
            "is why they're no longer tied. SAM3 solves a different kind of task (open-vocabulary, "
            "text-driven) rather than plain point/box masks, so treat its score as a rough guide only.",
            fg=TEXT_MUTED, bg=BG, font=("Sans", 9),
        ).pack(anchor="w", fill="x", pady=(0, 14))

        nav_row(parent, app, back_to=2, side="bottom")

        scroller = ScrollableFrame(parent)
        scroller.pack(fill="both", expand=True)

        rec_key = recommended_model_key(app.hw)

        for family in ("SAM1", "SAM2", "SAM3"):
            header = tk.Frame(scroller.inner, bg=BG)
            header.pack(fill="x", pady=(14, 6))
            arrow = tk.Label(header, text="▾", bg=BG, fg=ACCENT, font=("Sans", 12, "bold"), cursor="hand2")
            arrow.pack(side="left", padx=(0, 8))
            title_lbl = tk.Label(header, text=family, bg=BG, fg=TEXT, font=("Sans", 13, "bold"), cursor="hand2")
            title_lbl.pack(side="left")

            section_body = tk.Frame(scroller.inner, bg=BG)
            section_body.pack(fill="x")

            state = {"open": True}

            def toggle(_e=None, b=section_body, a=arrow, s=state):
                if s["open"]:
                    b.pack_forget()
                    a.config(text="▸")
                else:
                    b.pack(fill="x")
                    a.config(text="▾")
                s["open"] = not s["open"]

            arrow.bind("<Button-1>", toggle)
            title_lbl.bind("<Button-1>", toggle)

            if family != "SAM3":
                RoundedButton(header, "Download all", icon="download", variant="secondary", width=160,
                              command=lambda fam=family: self.on_download_all(fam)).pack(side="right")
                for spec in [m for m in MODEL_REGISTRY if m.family == family]:
                    self.rows.append(ModelRow(section_body, app, spec, recommended=(spec.key == rec_key)))
            else:
                sam3_card = RoundedCard(section_body)
                sam3_card.pack(fill="x", pady=(6, 20))
                self._build_sam3_panel(sam3_card.body)
                sam3_card.finalize()

        # All rows/cards/buttons now exist — attach the wheel-scroll
        # handlers to the whole subtree so scrolling works no matter which
        # widget happens to be under the pointer (see ScrollableFrame).
        scroller.bind_mousewheel_recursive()

    def refresh_rows(self):
        """Update every model row in place — no widgets are destroyed, so
        the list's scroll position is left exactly where the user had it."""
        for row in self.rows:
            if row.card.winfo_exists():
                row.render()

    def refresh_sam3_panel(self):
        """Update the SAM3 card's installed/not-installed bits in place —
        the same in-place idiom as refresh_rows(), for the same reason: a
        full self.app.show_step(3) rebuild used to run after every SAM3
        download/remove/transformers-setup, which threw away the whole
        scrollable Models list and rebuilt it from scratch at scroll
        position 0 — i.e. exactly the "jumps back to the top" complaint."""
        if not hasattr(self, "sam3_status_lbl") or not self.sam3_status_lbl.winfo_exists():
            return
        spec = next(m for m in MODEL_REGISTRY if m.family == "SAM3")
        installed = model_installed(spec)
        if installed:
            self.sam3_status_lbl.configure(text="Installed")
            self.sam3_status_lbl.pack(anchor="w", pady=(4, 0))
        else:
            self.sam3_status_lbl.configure(text="")
            self.sam3_status_lbl.pack_forget()
        self._sync_sam3_download_enabled()
        self.sam3_remove_btn.set_enabled(installed)

    def on_download_all(self, family):
        specs = [m for m in MODEL_REGISTRY if m.family == family and not model_installed(m)]
        if not specs:
            themed_info(self.app.root, "Nothing to do", f"All {family} models are already installed.")
            return
        for spec in specs:
            self.app.download_manager.enqueue(spec)

    def _build_sam3_panel(self, body):
        app = self.app
        spec = next(m for m in MODEL_REGISTRY if m.family == "SAM3")
        installed = model_installed(spec)

        top = tk.Frame(body, bg=CARD_BG)
        top.pack(fill="x")
        left = tk.Frame(top, bg=CARD_BG)
        left.pack(side="left", fill="x", expand=True)
        name_row = tk.Frame(left, bg=CARD_BG)
        name_row.pack(anchor="w")
        tk.Label(name_row, text=spec.label, bg=CARD_BG, fg=TEXT, font=("Sans", 12, "bold")).pack(side="left")
        tk.Label(name_row, text=f"   {spec.size}", bg=CARD_BG, fg=TEXT_MUTED, font=("Sans", 9)).pack(side="left")
        rating_widget(left, spec.quality, spec.speed, bg=CARD_BG).pack(anchor="w", pady=(4, 0))
        # Always created (unlike the old conditional tk.Label) so
        # refresh_sam3_panel() can just flip its text/visibility in place
        # after a download/remove finishes, instead of the caller having to
        # tear down and rebuild this whole panel (and, with it, reset the
        # Models list's scroll position back to the top).
        self.sam3_status_lbl = tk.Label(left, text="Installed" if installed else "", bg=CARD_BG, fg=SUCCESS, font=("Sans", 9, "bold"))
        if installed:
            self.sam3_status_lbl.pack(anchor="w", pady=(4, 0))

        autowrap_label(
            body, "Gated on Hugging Face — request access, get approved, then paste a token below.",
            fg=TEXT_MUTED, bg=CARD_BG, font=("Sans", 9),
        ).pack(anchor="w", fill="x", pady=(12, 14))

        row1 = tk.Frame(body, bg=CARD_BG)
        row1.pack(fill="x", pady=(0, 10))
        RoundedButton(row1, "Request access on Hugging Face", icon="link", variant="secondary", width=270, command=self.on_open_hf).pack(side="left")
        RoundedButton(row1, "Install / upgrade transformers", icon="box", variant="secondary", width=240, command=self.on_setup_transformers).pack(side="left", padx=8)

        row2 = tk.Frame(body, bg=CARD_BG)
        row2.pack(fill="x")
        tk.Label(row2, text="HF token", bg=CARD_BG, fg=TEXT, font=("Sans", 10, "bold")).pack(side="left")
        self.hf_token = tk.StringVar()
        hf_entry = ttk.Entry(row2, textvariable=self.hf_token, show="*", width=34, font=("Sans", 10))
        hf_entry.pack(side="left", padx=8, ipady=3)
        flatten_entry(hf_entry)
        self.sam3_download_btn = RoundedButton(
            row2, "Download", icon="download", variant="success", width=140, command=self.on_download_sam3,
            on_blocked=lambda: show_snackbar(self.app, "Enter a valid Hugging Face token first", tone="warn"),
        )
        self.sam3_download_btn.pack(side="left", padx=(0, 8))
        self.sam3_remove_btn = RoundedButton(row2, "Remove", icon="trash", variant="danger", width=130, command=self.on_remove_sam3)
        self.sam3_remove_btn.pack(side="left")
        self.sam3_download_btn.set_enabled((not installed) and bool(self.hf_token.get().strip()))
        self.sam3_remove_btn.set_enabled(installed)

        self.hf_token.trace_add("write", lambda *_a: self._sync_sam3_download_enabled())

    def _sync_sam3_download_enabled(self):
        spec = next(m for m in MODEL_REGISTRY if m.family == "SAM3")
        installed = model_installed(spec)
        token_ok = bool(self.hf_token.get().strip())
        self.sam3_download_btn.set_enabled((not installed) and token_ok)

    def on_open_hf(self):
        webbrowser.open(SAM3_HF_PAGE)

    def on_setup_transformers(self):
        token = self.hf_token.get().strip()
        if not token:
            themed_info(
                self.app.root, "Token needed first",
                "Paste your Hugging Face access token in the field below before installing — this step "
                "sets up the packages needed to actually use it.",
            )
            return

        def task(job: Job):
            if not backend_ready():
                job.log("Set up the Python backend first (previous step).")
                return
            pip = os.path.join(VENV_DIR, "bin", "pip")
            job.log("Installing/upgrading transformers + huggingface_hub (all SAM3 needs)")
            job.run_cmd([pip, "install", "-U", "transformers", "huggingface_hub"])
            job.log("Done.")

        # No on_done: nothing this step shows depends on transformers being
        # installed, so there is nothing to refresh — the default
        # refresh_all() would otherwise rebuild the whole Models step (and
        # its scroll position) for a change with no visible effect on it.
        self.app.run_in_background(task, on_done=lambda: None)

    def on_download_sam3(self):
        token = self.hf_token.get().strip()
        if not token:
            show_snackbar(self.app, "Enter a valid Hugging Face token first", tone="warn")
            return
        if not backend_ready():
            themed_info(self.app.root, "Backend missing", "Set up the Python backend first.")
            return

        outcome = {"ok": False, "tag": None}

        def task(job: Job):
            dest = os.path.join(MODELS_DIR, "sam3")
            os.makedirs(dest, exist_ok=True)
            script = build_sam3_download_script(dest, token)
            job.log(f"Downloading {SAM3_HF_REPO_ID} to {dest} (several GB, be patient)")
            rc, lines = job.run_cmd_capture([VENV_PYTHON, "-c", script])
            outcome["ok"] = rc == 0
            outcome["tag"] = classify_sam3_failure(lines)
            job.log("SAM3 checkpoint ready." if outcome["ok"] else "Download failed.")

        def done():
            self.refresh_sam3_panel()
            if not outcome["ok"]:
                themed_info(self.app.root, "Download failed", sam3_failure_message(outcome["tag"]))

        self.app.run_in_background(task, on_done=done)

    def on_remove_sam3(self):
        dest = os.path.join(MODELS_DIR, "sam3")
        if not themed_confirm(self.app.root, "Remove model", f"Delete {dest}?"):
            return

        def task(job: Job):
            try:
                shutil.rmtree(dest)
                if os.path.exists(dest):
                    job.log(f"WARNING: {dest} still exists after removal attempt (check permissions).")
                else:
                    job.log(f"Removed {dest}")
            except Exception as e:
                job.log(f"ERROR removing {dest}: {e}")

        self.app.run_in_background(task, on_done=self.refresh_sam3_panel)


def main():
    root = tk.Tk()
    InstallerApp(root)
    try:
        root.mainloop()
    finally:
        self_destruct_if_ephemeral()


if __name__ == "__main__":
    main()
