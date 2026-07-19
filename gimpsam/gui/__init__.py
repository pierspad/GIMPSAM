"""The optional GUI (CustomTkinter) — same engine, theme and widget set as
LazyGimp's installer, restricted to the SAM domain:

    theme.py     design tokens — every color, font, appearance setting
    icons.py     vector icons (Pillow-antialiased when available)
    helpers.py   drawing/layout primitives
    widgets.py   rounded cards/buttons on the CustomTkinter engine
    dialogs.py   themed dialogs and the snackbar
    state.py     "what's installed" summary helpers
    app.py       GimpSamApp — plumbing + page mixins composition
    pages/       one module per screen (landing / sam setup / progress)

Only this __init__ is safe to import headless: the submodules assume a
working Tk + customtkinter and are imported lazily by launch_gui(), so
`python3 installer.py status` keeps working on a box with neither.

The prebuilt binary bundles customtkinter (and Pillow); from a source
checkout or the .pyz the GUI needs one `pip install customtkinter`.
"""
from __future__ import annotations

import sys

from ..compat import _CTK_OK, _PIL_OK, _TK_OK, ctk
from ..util import _self_destruct_if_ephemeral


def launch_gui():
    if not _TK_OK:
        print("[fail] Tkinter is not available in this Python — install python3-tk (or the equivalent "
              "package for your distro) to use the graphical installer, or use the CLI: "
              "python3 installer.py --help", file=sys.stderr)
        sys.exit(1)
    if not _CTK_OK:
        print("[fail] The GUI needs the customtkinter package:\n"
              "         pip install customtkinter\n"
              "       (the prebuilt gimpsam-linux-x86_64 binary ships it already, and the\n"
              "       CLI works without it: python3 installer.py --help)", file=sys.stderr)
        sys.exit(1)
    if not _PIL_OK:
        print("[note] icons render crisper with Pillow — pip install pillow", file=sys.stderr)
    from .app import GimpSamApp
    from .theme import BG
    ctk.set_appearance_mode("dark")
    root = ctk.CTk(fg_color=BG)
    GimpSamApp(root)
    try:
        root.mainloop()
    finally:
        _self_destruct_if_ephemeral()
