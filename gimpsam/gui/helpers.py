"""Drawing and layout primitives shared by widgets and pages."""

from __future__ import annotations

from ..compat import tk
from .theme import ACCENT, CARD_BG, CARD_BORDER, F_SMALL, TEXT_MUTED


def _rounded_points(x1, y1, x2, y2, r):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]

def draw_round_rect(canvas, x1, y1, x2, y2, r=16, **kwargs):
    return canvas.create_polygon(_rounded_points(x1, y1, x2, y2, r), smooth=True, **kwargs)

def autowrap_label(parent, text, fg=TEXT_MUTED, bg=None, font=F_SMALL, justify="left"):
    lbl = tk.Label(parent, text=text, fg=fg, bg=bg or parent["bg"], font=font, justify=justify, anchor="w")

    def _resize(event):
        new_wrap = max(60, event.width - 4)
        if lbl.cget("wraplength") != new_wrap:
            lbl.configure(wraplength=new_wrap)

    lbl.bind("<Configure>", _resize)
    return lbl


def rating_widget(parent, quality, speed, bg=CARD_BG):
    row = tk.Frame(parent, bg=bg)

    def dots(container, score):
        for i in range(5):
            c = tk.Canvas(container, width=10, height=10, highlightthickness=0, bd=0, bg=bg)
            c.pack(side="left", padx=1)
            color = ACCENT if i < score else CARD_BORDER
            c.create_oval(1, 1, 9, 9, fill=color, outline="")

    tk.Label(row, text="Quality", bg=bg, fg=TEXT_MUTED, font=F_SMALL).pack(side="left", padx=(0, 4))
    qf = tk.Frame(row, bg=bg)
    qf.pack(side="left", padx=(0, 16))
    dots(qf, quality)
    tk.Label(row, text="Speed", bg=bg, fg=TEXT_MUTED, font=F_SMALL).pack(side="left", padx=(0, 4))
    sf = tk.Frame(row, bg=bg)
    sf.pack(side="left")
    dots(sf, speed)
    return row
