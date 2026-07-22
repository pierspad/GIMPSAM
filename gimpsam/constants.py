from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Where things live on disk.
#
# BACKEND_DIR deliberately stays under .../lazygimp/segany: it is the path
# every prior GIMPSAM shell install AND every LazyGimp install has always
# used, so upgrading to this package never orphans an already-downloaded
# multi-GB model. Renaming it would strand those checkpoints.
# ---------------------------------------------------------------------------

HOME = os.path.expanduser("~")
XDG_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
XDG_DATA_HOME = os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")
XDG_CACHE_HOME = os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache")

BACKEND_DIR = os.path.join(XDG_DATA_HOME, "lazygimp", "segany")
VENV_DIR = os.path.join(BACKEND_DIR, "venv")
MODELS_DIR = os.path.join(BACKEND_DIR, "models")
VENV_PYTHON = os.path.join(VENV_DIR, "bin", "python3")
VENV_PIP = os.path.join(VENV_DIR, "bin", "pip")

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isdir(HERE):
        HERE = None
except NameError:
    HERE = None

# --- upstream locations ----------------------------------------------------

GIMPSAM_REPO = "pierspad/GIMPSAM"
SEGANY_README = f"https://github.com/{GIMPSAM_REPO}#readme"
PLUGIN_FILES = ["seganyplugin.py", "seganybridge.py"]

SAM1_PIP_SPEC = "git+https://github.com/facebookresearch/segment-anything.git"
SAM2_PIP_SPEC = "git+https://github.com/facebookresearch/segment-anything-2.git"
SAM3_HF_REPO_ID = "facebook/sam3.1"
SAM3_HF_PAGE = f"https://huggingface.co/{SAM3_HF_REPO_ID}"

# PyTorch wheel indexes offered in the SAM setup. To refresh this list:
# every entry is a directory under https://download.pytorch.org/whl/ —
# checking which ones exist is one command:
#   for i in cpu cu126 cu128 cu130 rocm6.4 rocm7.2; do
#     curl -so /dev/null -w "$i %{http_code}\n" https://download.pytorch.org/whl/$i/torch/
#   done
# (kept as explicit pins so an unattended install can never silently switch
# to a wheel index that doesn't exist yet for the user's GPU stack)
TORCH_INDEX_URLS = {
    "CPU (universal, smaller download)": "https://download.pytorch.org/whl/cpu",
    "NVIDIA CUDA 13.2 (latest)": "https://download.pytorch.org/whl/cu132",
    "NVIDIA CUDA 13.0": "https://download.pytorch.org/whl/cu130",
    "NVIDIA CUDA 12.8": "https://download.pytorch.org/whl/cu128",
    "AMD ROCm 7.2 (latest)": "https://download.pytorch.org/whl/rocm7.2",
    "AMD ROCm 6.4": "https://download.pytorch.org/whl/rocm6.4",
    "Intel Arc / XPU (Intel GPU)": "https://download.pytorch.org/whl/xpu",
}
