"""Optional-dependency guards (Tk for the GUI, Pillow for pretty icons).

Import `tk`, `ttk`, ... from here instead of guarding every module:
on a headless box they are simply None and `_TK_OK` is False — the CLI
works either way, only `launch_gui()` refuses to start.
"""
from __future__ import annotations

try:
    import tkinter as tk
    from tkinter import simpledialog, ttk
    _TK_OK = True
except Exception:  # pragma: no cover - headless boxes
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    simpledialog = None  # type: ignore[assignment]
    _TK_OK = False

try:
    from PIL import Image, ImageDraw, ImageTk
    _PIL_OK = True
except ImportError:  # pragma: no cover - Pillow is optional
    Image = ImageDraw = ImageTk = None  # type: ignore[assignment]
    _PIL_OK = False

# CustomTkinter powers the GUI's look. It is bundled in the prebuilt
# binary; from a source checkout / the .pyz it's one `pip install
# customtkinter` away. The CLI never needs it.
try:
    import customtkinter as ctk
    _CTK_OK = _TK_OK
except ImportError:  # pragma: no cover
    ctk = None  # type: ignore[assignment]
    _CTK_OK = False
