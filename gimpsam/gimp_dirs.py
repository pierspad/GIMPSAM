from __future__ import annotations

from .constants import XDG_CONFIG_HOME
from typing import Optional
import os
import re
import shutil
import subprocess

# ---------------------------------------------------------------------------
# GIMP per-user directories — just enough detection to know where plug-ins
# go. Nothing here hardcodes a GIMP version: the config directory
# (3.0, 3.2, ...) is always resolved at runtime.
# ---------------------------------------------------------------------------

import glob

def find_gimp_binary() -> Optional[str]:
    return shutil.which("gimp") or shutil.which("gimp-3.0") or shutil.which("gimp-2.10")


def gimp_appimage_present() -> bool:
    appimage_dir = os.environ.get("LAZYGIMP_APPIMAGE_DIR") or os.path.join(os.path.expanduser("~"), "Applications")
    return len(glob.glob(os.path.join(appimage_dir, "GIMP-*.AppImage"))) > 0 or os.path.isfile(os.path.join(appimage_dir, "GIMP.AppImage"))


def is_gimp_installed() -> bool:
    return bool(find_gimp_binary()) or gimp_appimage_present()


def gimp_version_string() -> Optional[str]:
    bin_ = find_gimp_binary()
    if not bin_:
        return None
    try:
        out = subprocess.run([bin_, "--version"], capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    m = re.search(r"(\d+)\.(\d+)(?:\.\d+)?", out.stdout or "")
    return f"{m.group(1)}.{m.group(2)}" if m else None


def gimp_config_base() -> str:
    return os.path.join(XDG_CONFIG_HOME, "GIMP")


def _version_key(name: str):
    try:
        return tuple(int(p) for p in name.split("."))
    except ValueError:
        return (0,)


def gimp_version_dirs() -> list[str]:
    base = gimp_config_base()
    if not os.path.isdir(base):
        return []
    names = [n for n in os.listdir(base) if re.fullmatch(r"\d+\.\d+", n) and os.path.isdir(os.path.join(base, n))]
    names.sort(key=_version_key)
    return [os.path.join(base, n) for n in names]


def gimp_live_config_dir() -> Optional[str]:
    """The config dir GIMP actually reads, proven by a live `pluginrc` —
    more reliable than trusting `gimp --version`, whose reported MAJOR.MINOR
    is not guaranteed to equal the profile directory name GIMP actually
    uses."""
    for d in reversed(gimp_version_dirs()):
        if os.path.isfile(os.path.join(d, "pluginrc")):
            return d
    return None


def gimp_config_dir(version_hint: Optional[str] = None) -> Optional[str]:
    base = gimp_config_base()
    if version_hint:
        m = re.search(r"(\d+)\.(\d+)", version_hint)
        if m:
            return os.path.join(base, f"{m.group(1)}.{m.group(2)}")
    live = gimp_live_config_dir()
    if live:
        return live
    ver = gimp_version_string()
    if ver:
        return os.path.join(base, ver)
    dirs = gimp_version_dirs()
    return dirs[-1] if dirs else None


def gimp_plugins_dir(version_hint: Optional[str] = None) -> Optional[str]:
    cfg = gimp_config_dir(version_hint)
    return os.path.join(cfg, "plug-ins") if cfg else None


def invalidate_gimp_plugin_cache(job) -> None:
    for d in gimp_version_dirs():
        pluginrc = os.path.join(d, "pluginrc")
        if os.path.isfile(pluginrc):
            try:
                os.remove(pluginrc)
                job.log(f"Cleared {pluginrc} so GIMP rescans plug-ins on next launch")
            except OSError as e:
                job.log(f"Could not clear {pluginrc}: {e} (not fatal)")
