from __future__ import annotations

from .constants import (BACKEND_DIR, MODELS_DIR, SAM1_PIP_SPEC, SAM2_PIP_SPEC, SEGANY_README,
                        VENV_DIR, VENV_PIP, VENV_PYTHON)
from .gimp_dirs import gimp_plugins_dir
from .models import MODEL_BY_KEY, ModelSpec, model_path
import glob
import os
import shutil
import subprocess
import sys

# ---------------------------------------------------------------------------
# SAM Python backend — venv, PyTorch, SAM1+SAM2 packages (the bridge imports
# both unconditionally), checkpoint downloads, self-test.
#
# Every function takes a duck-typed `job` (log/run_cmd/run_cmd_capture/
# download) — gimpsam.job.Job for CLI use, LazyGimp's Job from its GUI.
# ---------------------------------------------------------------------------

def venv_exists() -> bool:
    return os.path.isfile(VENV_PYTHON) and os.access(VENV_PYTHON, os.X_OK)


def backend_ready() -> bool:
    if not venv_exists():
        return False
    try:
        r = subprocess.run([VENV_PYTHON, "-c", "import torch"], capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def install_sam_backend(job, torch_index: str) -> bool:
    os.makedirs(BACKEND_DIR, exist_ok=True)
    if not venv_exists():
        job.log(f"Creating virtualenv at {VENV_DIR}")
        if job.run_cmd([sys.executable, "-m", "venv", VENV_DIR]) != 0:
            job.log("Failed to create the virtualenv (is python3-venv installed?).")
            return False
    else:
        job.log(f"Reusing existing virtualenv at {VENV_DIR}")

    job.run_cmd([VENV_PIP, "install", "--upgrade", "pip"])
    job.log(f"Installing PyTorch from {torch_index}")
    if job.run_cmd([VENV_PIP, "install", "torch", "torchvision", "--index-url", torch_index]) != 0:
        job.log("PyTorch failed to install — almost always a network problem reaching "
                "download.pytorch.org rather than a bug here. Check your connection and retry.")
        return False
    job.log("Installing image dependencies (numpy, pillow, opencv)")
    job.run_cmd([VENV_PIP, "install", "numpy", "pillow", "opencv-python-headless"])
    job.log("Installing SAM1 backend (segment-anything)")
    job.run_cmd([VENV_PIP, "install", SAM1_PIP_SPEC])
    job.log("Installing SAM2 backend (segment-anything-2) — builds from source, can take a few minutes")
    if job.run_cmd([VENV_PIP, "install", SAM2_PIP_SPEC]) != 0:
        job.log("SAM2 failed to build/install — SAM1 models will still work, but the plug-in's bridge "
                f"imports both unconditionally. Install a C/C++ toolchain and retry — see {SEGANY_README}")
    job.log("Installing/upgrading huggingface_hub (needed for SAM 3.1)")
    job.run_cmd([VENV_PIP, "install", "-U", "huggingface_hub"])
    job.log("Python backend ready.")
    return True


def remove_sam_backend(job) -> bool:
    if os.path.isdir(BACKEND_DIR):
        shutil.rmtree(BACKEND_DIR)
        job.log(f"SAM backend removed ({BACKEND_DIR})")
    else:
        job.log("No SAM backend found.")
    return True


def install_sam3_transformers(job) -> bool:
    if not backend_ready():
        job.log("Set up the Python backend first.")
        return False
    job.log("Installing/upgrading transformers (needed to run SAM 3.1)")
    return job.run_cmd([VENV_PIP, "install", "-U", "transformers", "huggingface_hub"]) == 0


def bridge_self_test(job, primary: ModelSpec) -> None:
    d = gimp_plugins_dir()
    plugin_dir = os.path.join(d, "seganyplugin") if d else None
    if not plugin_dir or not os.path.isdir(plugin_dir):
        return
    bridges = glob.glob(os.path.join(plugin_dir, "seganybridge*.py"))
    if not bridges:
        job.log("Bridge script not found; skipping self-test.")
        return
    job.log("Running the bridge self-test (first run compiles kernels, be patient)...")
    try:
        r = subprocess.run([VENV_PYTHON, bridges[0], "auto", model_path(primary)],
                            capture_output=True, text=True, cwd=plugin_dir, timeout=300)
        out = (r.stdout or "") + (r.stderr or "")
        if "success" in out.lower():
            job.log("Bridge self-test passed — the SAM backend is fully functional.")
        else:
            job.log(f"Bridge self-test did not report success — see {SEGANY_README} for troubleshooting.")
    except Exception as e:
        job.log(f"Bridge self-test could not run: {e}")


def write_sam_info(models: list[str]) -> str:
    os.makedirs(BACKEND_DIR, exist_ok=True)
    primary = MODEL_BY_KEY[models[0]]
    info = os.path.join(BACKEND_DIR, "INFO.txt")
    with open(info, "w", encoding="utf-8") as fh:
        fh.write(
            "GIMPSAM — Segment Anything backend\n"
            "==================================\n\n"
            "On the FIRST run of the plug-in (GIMP -> Image -> Segment Anything Layers),\n"
            "fill in these two fields -- GIMP remembers them afterwards:\n\n"
            f"  Python3 Path:    {VENV_PYTHON}\n"
            f"  Checkpoint Path: {model_path(primary)}\n\n"
            "Model Type: leave \"Auto\" in the dialog -- inferred from the checkpoint filename.\n\n"
            f"Installed model(s): {', '.join(models)}\n"
            f"Checkpoints live in: {MODELS_DIR}\n"
        )
    return info
