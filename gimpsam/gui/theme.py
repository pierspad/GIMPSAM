"""Design tokens — every color, font and ttk style in one place.

Restyling the whole app (palette swap, font change) is an edit to THIS
file only: no other gui module hardcodes a color or a font tuple.
"""
from __future__ import annotations

from ..compat import tk, ttk

# --- dark palette ----------------------------------------------------------
BG = "#1b1d21"
CARD_BG = "#26282e"
CARD_BORDER = "#35373e"
TEXT = "#e7e8ea"
TEXT_MUTED = "#9a9da4"
ACCENT = "#4dc3f0"
ACCENT_HOVER = "#6fd0f5"
ACCENT_TEXT = "#08222b"
SUCCESS = "#3fbf7f"
SUCCESS_HOVER = "#57cf93"
SUCCESS_TEXT = "#08210f"
DANGER = "#ee5a5f"
DANGER_HOVER = "#f27478"
DANGER_TEXT = "#2b0b0c"
WARNING = "#f2a93c"
DISABLED_BG = "#34363c"
DISABLED_TEXT = "#6d7076"

FIELD_BG = "#303237"          # entries / comboboxes
SCROLLBAR = "#4a4d54"
LOG_BG = "#101114"            # install-progress log panel
SECONDARY_HOVER = "#3f424a"   # hover fill of secondary buttons

# tone colors for callouts / snackbars: tone -> (background, foreground)
TONE_COLORS = {
    "info": ("#16303a", "#7fd0f0"),
    "warn": ("#3a2e14", WARNING),
    "error": ("#3a1414", DANGER),
    "ok": ("#123522", SUCCESS),
}

# --- fonts -----------------------------------------------------------------
FONT_FAMILY = "Sans"
F_HERO = (FONT_FAMILY, 30, "bold")          # landing title
F_H1 = (FONT_FAMILY, 21, "bold")            # screen titles
F_H2 = (FONT_FAMILY, 19, "bold")            # page headers
F_H3 = (FONT_FAMILY, 17, "bold")            # wizard step title
F_CARD_TITLE = (FONT_FAMILY, 15, "bold")
F_DIALOG_TITLE = (FONT_FAMILY, 14, "bold")
F_ITEM_TITLE = (FONT_FAMILY, 13, "bold")
F_SECTION = (FONT_FAMILY, 12, "bold")
F_SUBTITLE = (FONT_FAMILY, 12)
F_BODY_B = (FONT_FAMILY, 11, "bold")
F_BODY = (FONT_FAMILY, 11)
F_SMALL_B = (FONT_FAMILY, 10, "bold")
F_SMALL = (FONT_FAMILY, 10)
F_MONO = ("Monospace", 10)

# base size for the vector icons; call sites scale from here so the whole
# icon set can be grown/shrunk in one place
ICON_SIZE = 20


def apply_style(root) -> None:
    """Window-level theming. Widget colors are passed explicitly from this
    module's tokens (see widgets.py), so there is deliberately little here:
    CustomTkinter's appearance mode is set in launch_gui(), and the ttk
    styles of the old engine are gone with the ttk widgets themselves."""
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TSeparator", background=CARD_BORDER)
