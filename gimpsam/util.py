from __future__ import annotations

import os
import re
import shutil
import sys


def clean_output_line(line: str) -> str:
    """Strip ANSI escape sequences (colors, cursor movements) and resolve
    carriage returns (keeping only the final overwritten text)."""
    ansi_escape = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    line = ansi_escape.sub('', line)
    if '\r' in line:
        parts = line.split('\r')
        non_empty = [p for p in parts if p.strip()]
        line = non_empty[-1] if non_empty else parts[-1]
    return line


def _install_artifact_paths() -> list[str]:
    """Paths that make up this installation, for --ephemeral self-destruction.

    Depending on how GIMPSAM was launched this is:
      * the PyInstaller binary   (frozen single-file build)
      * the zipapp archive       (gimpsam.pyz)
      * the source checkout      (gimpsam/ package + installer.py launcher)
    """
    if getattr(sys, "frozen", False):  # PyInstaller
        return [sys.executable]
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isdir(pkg_dir):
        # Running from inside an archive (zipapp): walk up to the archive file.
        probe = pkg_dir
        while probe and not os.path.isfile(probe):
            probe = os.path.dirname(probe)
        return [probe] if probe else []
    paths = [pkg_dir]
    launcher = os.path.join(os.path.dirname(pkg_dir), "installer.py")
    if os.path.isfile(launcher):
        paths.append(launcher)
    return paths


def _self_destruct_if_ephemeral() -> None:
    # The env var is authoritative when set (the GUI's "delete this
    # installer" checkbox writes it, so un-ticking beats --ephemeral);
    # otherwise the CLI flag decides.
    env = os.environ.get("GIMPSAM_INSTALLER_EPHEMERAL")
    ephemeral = (env == "1") if env is not None else ("--ephemeral" in sys.argv)
    if not ephemeral:
        return
    for path in _install_artifact_paths():
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.isfile(path):
                os.remove(path)
            pycache = os.path.join(os.path.dirname(path), "__pycache__")
            if os.path.isdir(pycache):
                shutil.rmtree(pycache, ignore_errors=True)
        except OSError:
            pass
