"""gimpsam — the Segment Anything backend for GIMP, as an importable package.

This package owns everything below the GIMP plug-in itself: the Python
virtualenv, PyTorch, the SAM1/SAM2/SAM3 model registry and checkpoint
downloads, and the plug-in file installation. It is the single source of
truth consumed both by this repository's own installer (installer.py, the
Tk wizard) via the CLI, and by LazyGimp, which imports it from a pinned
GitHub release to drive the same logic from its own GUI.

The version below is stamped by scripts/build_release_assets.sh at release
time; a git checkout always reads 0.0.0-dev.
"""

__version__ = "0.0.0-dev"
