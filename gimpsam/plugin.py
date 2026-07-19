from __future__ import annotations

from . import __version__
from .constants import GIMPSAM_REPO, HERE, PLUGIN_FILES, VENV_PYTHON
from .gimp_dirs import gimp_plugins_dir, invalidate_gimp_plugin_cache
from .models import ModelSpec, model_path
from typing import Optional
import json
import os
import shutil
import tempfile
import zipfile

# ---------------------------------------------------------------------------
# The GIMP plug-in files themselves (seganyplugin.py + seganybridge.py):
# resolve-then-copy into GIMP's plug-ins dir. Resolution order is
# local-first so a checkout always installs exactly what's on disk, and
# release-pinned otherwise so nobody silently installs whatever happens to
# be on main today:
#
#   1. $GIMPSAM_SRC_DIR (explicit override)
#   2. files sitting next to this package (a repo checkout, the release
#      src bundle, or LazyGimp's vendored copy — same layout in all three)
#   3. the GitHub source zipball at `ref` — the tag matching this
#      package's own stamped version, so code and plug-in always match
# ---------------------------------------------------------------------------

def default_ref() -> str:
    """The git ref this package's plug-in files should come from: its own
    release tag when running a stamped release, main for a dev checkout."""
    return "main" if __version__.startswith("0.0.0") else f"v{__version__}"


def plugin_installed() -> bool:
    d = gimp_plugins_dir()
    return bool(d) and os.path.isfile(os.path.join(d, "seganyplugin", "seganyplugin.py"))


def _local_candidates() -> list[str]:
    dirs = []
    override = os.environ.get("GIMPSAM_SRC_DIR")
    if override:
        dirs.append(override)
    if HERE:
        dirs.append(os.path.dirname(HERE))  # repo root / bundle root, next to the package
    return dirs


def resolve_plugin_sources(job, ref: Optional[str] = None) -> dict[str, str]:
    for d in _local_candidates():
        if all(os.path.isfile(os.path.join(d, f)) for f in PLUGIN_FILES):
            return {f: os.path.join(d, f) for f in PLUGIN_FILES}

    ref = ref or default_ref()
    url = f"https://github.com/{GIMPSAM_REPO}/archive/{ref}.zip"
    tmp = tempfile.mkdtemp(prefix="gimpsam-src-")
    zip_path = os.path.join(tmp, "gimpsam.zip")
    job.log(f"Fetching plug-in files from {GIMPSAM_REPO}@{ref}")
    if not job.download(url, zip_path):
        raise RuntimeError(f"could not download {url}")
    extracted = os.path.join(tmp, "extracted")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extracted)
    for root, _dirs, files in os.walk(extracted):
        if all(f in files for f in PLUGIN_FILES):
            return {f: os.path.join(root, f) for f in PLUGIN_FILES}
    raise RuntimeError(f"plug-in files {PLUGIN_FILES} not found inside {url}")


def install_plugin(job, ref: Optional[str] = None) -> bool:
    dest_dir = gimp_plugins_dir()
    if not dest_dir:
        job.log("ERROR: no GIMP plug-ins directory found — install GIMP first.")
        return False
    try:
        sources = resolve_plugin_sources(job, ref)
    except Exception as e:
        job.log(f"ERROR: {e}")
        return False
    dest = os.path.join(dest_dir, "seganyplugin")
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    for fname, path in sources.items():
        shutil.copy2(path, dest)
        os.chmod(os.path.join(dest, fname), 0o755)
    invalidate_gimp_plugin_cache(job)
    job.log(f"SAM plug-in installed into {dest} — find it under "
            "Image → Segment Anything Layers after a GIMP restart")
    return True


def remove_plugin(job) -> bool:
    d = gimp_plugins_dir()
    dest = os.path.join(d, "seganyplugin") if d else None
    if dest and os.path.isdir(dest):
        shutil.rmtree(dest)
        invalidate_gimp_plugin_cache(job)
        job.log(f"Removed {dest}")
    else:
        job.log("SAM plug-in was not installed.")
    return True


def write_plugin_settings(primary: ModelSpec) -> None:
    d = gimp_plugins_dir()
    if not d:
        return
    plugin_dir = os.path.join(d, "seganyplugin")
    if not os.path.isdir(plugin_dir):
        return
    settings = {
        "pythonPath": VENV_PYTHON,
        "checkPtPath": model_path(primary),
        "modelType": "Auto",
    }
    with open(os.path.join(plugin_dir, "segany_settings.json"), "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
