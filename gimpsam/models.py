from __future__ import annotations

from .constants import MODELS_DIR
from dataclasses import dataclass
from typing import Optional
import os

# ---------------------------------------------------------------------------
# SAM model registry — the single source of truth for every SAM checkpoint
# this backend knows how to fetch. LazyGimp renders its model cards straight
# from this list, so adding an entry here is all it takes to surface a new
# model everywhere.
# ---------------------------------------------------------------------------

@dataclass
class ModelSpec:
    key: str
    family: str  # "SAM1", "SAM2", "SAM3"
    label: str
    size: str
    quality: int  # 1-5, rough/comparable within a family
    speed: int  # 1-5
    filename: Optional[str] = None  # None only for SAM3 (a folder, not a file)
    url: Optional[str] = None  # None only for SAM3 (gated — downloaded via HF token)


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
MODEL_BY_KEY = {m.key: m for m in MODEL_REGISTRY}


def model_path(spec: ModelSpec) -> str:
    if spec.family == "SAM3":
        return os.path.join(MODELS_DIR, "sam3")
    return os.path.join(MODELS_DIR, spec.filename)


def model_installed(spec: ModelSpec) -> bool:
    p = model_path(spec)
    if spec.family == "SAM3":
        # snapshot_download() failing partway through (e.g. a 403 on a
        # gated/unapproved repo) can still leave a few small metadata files
        # behind — "folder is non-empty" would then wrongly read as
        # installed. config.json is one of the last files HF writes, so its
        # presence is a real signal the snapshot completed.
        return os.path.isdir(p) and os.path.isfile(os.path.join(p, "config.json"))
    return os.path.isfile(p)


def any_model_installed() -> bool:
    return any(model_installed(m) for m in MODEL_REGISTRY)
