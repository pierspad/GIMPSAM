from __future__ import annotations

from .constants import TORCH_INDEX_URLS
from dataclasses import dataclass
from typing import Optional
import os
import platform
import shutil
import subprocess

# ---------------------------------------------------------------------------
# Hardware detection — used only to pick a sane default SAM model and
# PyTorch wheel index.
# ---------------------------------------------------------------------------

@dataclass
class Hardware:
    cpu_cores: int
    python_version: str
    gpu: Optional[dict]


def detect_gpu() -> Optional[dict]:
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            line = next((ln for ln in out.stdout.splitlines() if ln.strip()), None)
            if line:
                return {"vendor": "NVIDIA", "name": line.strip(), "driver_ready": True}
        except Exception:
            pass
    if shutil.which("rocminfo"):
        try:
            out = subprocess.run(["rocminfo"], capture_output=True, text=True, timeout=5)
            name = next(
                (ln.split(":", 1)[1].strip() for ln in out.stdout.splitlines() if "Marketing Name" in ln), None,
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


def recommended_model_key(hw: Hardware) -> str:
    return "sam2_hiera_base_plus" if (hw.gpu and hw.gpu.get("driver_ready")) else "sam2_hiera_small"


def recommended_torch_index(hw: Hardware) -> str:
    if hw.gpu and hw.gpu.get("driver_ready"):
        if "NVIDIA" in hw.gpu["vendor"]:
            return TORCH_INDEX_URLS["NVIDIA CUDA 12.8"]
        if "AMD" in hw.gpu["vendor"]:
            return TORCH_INDEX_URLS["AMD ROCm 7.2 (latest)"]
    return TORCH_INDEX_URLS["CPU (universal, smaller download)"]
