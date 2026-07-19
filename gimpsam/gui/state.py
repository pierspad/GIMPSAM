"""What's on this system, in the landing screen's vocabulary."""

from __future__ import annotations

from ..backend import backend_ready, venv_exists
from ..constants import BACKEND_DIR
from ..models import MODEL_REGISTRY, model_installed
from ..plugin import plugin_installed
import os


def anything_installed() -> bool:
    return plugin_installed() or os.path.isdir(BACKEND_DIR)


def status_lines() -> list[tuple[bool, str]]:
    """(ok, text) pairs for the landing/setup status strip."""
    installed_models = [m.label for m in MODEL_REGISTRY if model_installed(m)]
    backend = backend_ready()
    return [
        (plugin_installed(), "GIMP plug-in " + ("installed" if plugin_installed() else "not installed")),
        (backend, "Python backend " + ("ready" if backend else
                                       ("present but broken" if venv_exists() else "not installed"))),
        (bool(installed_models), "Models: " + (", ".join(installed_models) if installed_models else "none")),
    ]
