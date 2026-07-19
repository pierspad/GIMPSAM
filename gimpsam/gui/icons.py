"""Small monochrome vector icons — one geometry definition per icon
against a tiny backend-agnostic painter, targeting either a Tk Canvas
(no anti-aliasing) or a Pillow surface rendered at 4x and downsampled
(genuinely anti-aliased). Pillow stays optional so the GUI has no hard
dependency beyond Tkinter itself."""

from __future__ import annotations

from ..compat import Image, ImageDraw, ImageTk, _PIL_OK, tk
from .theme import TEXT, WARNING
import math


class _Painter:
    def __init__(self, target, pil=False):
        self.target = target
        self.pil = pil

    def line(self, pts, color, width=2):
        if self.pil:
            self.target.line(pts, fill=color, width=max(1, round(width)), joint="curve")
        else:
            self.target.create_line(*pts, fill=color, width=width, capstyle="round", joinstyle="round")

    def polygon(self, pts, color=None, outline=None, width=2):
        if self.pil:
            if color is not None:
                self.target.polygon(pts, fill=color)
            if outline is not None:
                self.target.polygon(pts, outline=outline, width=max(1, round(width)))
        else:
            self.target.create_polygon(*pts, fill=color or "", outline=outline or "", width=width)

    def rect(self, x1, y1, x2, y2, color=None, outline=None, width=2, radius=0):
        if self.pil:
            if radius > 0:
                self.target.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=color, outline=outline,
                                               width=max(1, round(width)))
            else:
                self.target.rectangle([x1, y1, x2, y2], fill=color, outline=outline, width=max(1, round(width)))
        else:
            self.target.create_rectangle(x1, y1, x2, y2, fill=color or "", outline=outline or "", width=width)

    def oval(self, x1, y1, x2, y2, color=None, outline=None, width=2):
        if self.pil:
            self.target.ellipse([x1, y1, x2, y2], fill=color, outline=outline, width=max(1, round(width)))
        else:
            self.target.create_oval(x1, y1, x2, y2, fill=color or "", outline=outline or "", width=width)

    def arc(self, x1, y1, x2, y2, start, extent, color, width=2):
        if self.pil:
            self.target.arc([x1, y1, x2, y2], start=-(start + extent), end=-start, fill=color,
                             width=max(1, round(width)))
        else:
            self.target.create_arc(x1, y1, x2, y2, start=start, extent=extent, style="arc", outline=color,
                                    width=width)

def _paint_icon(p: _Painter, cx, cy, kind, color, s, frame=0):
    w = max(1.6, s * 0.16)
    if kind == "gear":
        outer_r, inner_r = s, s * 0.6
        tooth_half = s * 0.42
        for i in range(8):
            ang = math.radians(i * 45)
            ca, sa = math.cos(ang), math.sin(ang)
            corners = []
            for rr, tt in ((inner_r, -tooth_half), (outer_r, -tooth_half), (outer_r, tooth_half),
                           (inner_r, tooth_half)):
                corners += [cx + rr * ca - tt * sa, cy + rr * sa + tt * ca]
            p.polygon(corners, color)
        p.oval(cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r, outline=color, width=s * 0.3)
    elif kind == "circle":
        p.oval(cx - s * 0.75, cy - s * 0.75, cx + s * 0.75, cy + s * 0.75, outline=color, width=w)
    elif kind == "appimage":
        p.polygon([
            cx - s * 0.7, cy - s * 0.4,
            cx + s * 0.4, cy - s * 0.7,
            cx + s * 0.7, cy + s * 0.4,
            cx - s * 0.4, cy + s * 0.7
        ], outline=color, width=w)
        p.polygon([
            cx - s * 0.2, cy + s * 0.3,
            cx, cy - s * 0.3,
            cx + s * 0.2, cy + s * 0.3
        ], outline=color, width=w)
    elif kind == "gimp":
        p.polygon([cx - s * 0.5, cy - s * 0.3, cx - s * 0.7, cy - s * 0.7, cx - s * 0.2, cy - s * 0.4], outline=color, width=w)
        p.polygon([cx + s * 0.2, cy - s * 0.4, cx + s * 0.7, cy - s * 0.7, cx + s * 0.5, cy - s * 0.3], outline=color, width=w)
        p.oval(cx - s * 0.6, cy - s * 0.4, cx + s * 0.6, cy + s * 0.5, outline=color, width=w)
        p.oval(cx - s * 0.85, cy - s * 0.1, cx - s * 0.5, cy + s * 0.25, color=color)
        p.oval(cx - s * 0.35, cy - s * 0.3, cx + s * 0.05, cy + s * 0.1, outline=color, width=w)
        p.oval(cx - s * 0.05, cy - s * 0.3, cx + s * 0.35, cy + s * 0.1, outline=color, width=w)
        p.oval(cx - s * 0.22, cy - s * 0.18, cx - s * 0.08, cy - s * 0.04, color=color)
        p.oval(cx + s * 0.08, cy - s * 0.18, cx + s * 0.22, cy - s * 0.04, color=color)
        p.arc(cx - s * 0.3, cy + s * 0.05, cx + s * 0.4, cy + s * 0.4, 200, 120, color, width=w)
    elif kind == "photogimp":
        p.polygon([cx - s * 0.5, cy - s * 0.3, cx - s * 0.7, cy - s * 0.7, cx - s * 0.2, cy - s * 0.4], outline=color, width=w)
        p.polygon([cx + s * 0.2, cy - s * 0.4, cx + s * 0.7, cy - s * 0.7, cx + s * 0.5, cy - s * 0.3], outline=color, width=w)
        p.oval(cx - s * 0.6, cy - s * 0.4, cx + s * 0.6, cy + s * 0.5, outline=color, width=w)
        p.oval(cx - s * 0.85, cy - s * 0.1, cx - s * 0.5, cy + s * 0.25, color=color)
        p.oval(cx - s * 0.35, cy - s * 0.3, cx + s * 0.05, cy + s * 0.1, outline=color, width=w)
        p.oval(cx - s * 0.05, cy - s * 0.3, cx + s * 0.35, cy + s * 0.1, outline=color, width=w)
        p.oval(cx - s * 0.22, cy - s * 0.18, cx - s * 0.08, cy - s * 0.04, color=color)
        p.oval(cx + s * 0.08, cy - s * 0.18, cx + s * 0.22, cy - s * 0.04, color=color)
        p.arc(cx - s * 0.3, cy + s * 0.05, cx + s * 0.4, cy + s * 0.4, 200, 120, color, width=w)
        p.line([cx + s * 0.05, cy + s * 0.25, cx + s * 0.65, cy + s * 0.55], color, width=max(2.5, s * 0.18))
        p.polygon([cx + s * 0.65, cy + s * 0.55, cx + s * 0.85, cy + s * 0.75, cx + s * 0.75, cy + s * 0.5], color=color)
    elif kind == "gmic":
        p.oval(cx - s * 0.8, cy + s * 0.4, cx + s * 0.8, cy + s * 0.7, outline=color, width=w)
        p.polygon([cx - s * 0.45, cy + s * 0.45, cx, cy - s * 0.75, cx + s * 0.45, cy + s * 0.45], outline=color, width=w)
        p.line([cx - s * 0.6, cy - s * 0.3, cx - s * 0.4, cy - s * 0.3], color, width=w)
        p.line([cx - s * 0.5, cy - s * 0.4, cx - s * 0.5, cy - s * 0.2], color, width=w)
        p.line([cx + s * 0.4, cy - s * 0.1, cx + s * 0.6, cy - s * 0.1], color, width=w)
        p.line([cx + s * 0.5, cy - s * 0.2, cx + s * 0.5, cy], color, width=w)
    elif kind == "batcher":
        p.rect(cx - s * 0.4, cy - s * 0.7, cx + s * 0.6, cy + s * 0.3, outline=color, width=w, radius=s * 0.15)
        p.rect(cx - s * 0.5, cy - s * 0.5, cx + s * 0.5, cy + s * 0.5, outline=color, width=w, radius=s * 0.15)
        p.rect(cx - s * 0.6, cy - s * 0.3, cx + s * 0.4, cy + s * 0.7, outline=color, width=w, radius=s * 0.15)
        p.oval(cx - s * 0.3, cy + s * 0.05, cx + s * 0.1, cy + s * 0.45, outline=color, width=w)
        p.line([cx - s * 0.1, cy + s * 0.15, cx - s * 0.1, cy + s * 0.35], color, width=w)
        p.line([cx - s * 0.2, cy + s * 0.25, cx, cy + s * 0.25], color, width=w)
    elif kind == "arch":
        p.polygon([cx, cy - s * 0.95, cx - s * 0.8, cy + s * 0.75, cx, cy + s * 0.35, cx + s * 0.8, cy + s * 0.75], outline=color, width=w)
        p.polygon([cx, cy - s * 0.4, cx - s * 0.45, cy + s * 0.45, cx, cy + s * 0.22, cx + s * 0.45, cy + s * 0.45], color=color)
    elif kind == "debian":
        p.oval(cx - s * 0.75, cy - s * 0.75, cx + s * 0.75, cy + s * 0.75, outline=color, width=w)
        p.arc(cx - s * 0.45, cy - s * 0.45, cx + s * 0.45, cy + s * 0.45, 90, 270, color, width=w)
        p.arc(cx - s * 0.2, cy - s * 0.2, cx + s * 0.2, cy + s * 0.2, 0, 180, color, width=w)
    elif kind == "ubuntu":
        p.oval(cx - s * 0.75, cy - s * 0.75, cx + s * 0.75, cy + s * 0.75, outline=color, width=w)
        for angle in (0, 120, 240):
            rad = math.radians(angle)
            px = cx + math.cos(rad) * s * 0.65
            py = cy + math.sin(rad) * s * 0.65
            p.oval(px - s * 0.18, py - s * 0.18, px + s * 0.18, py + s * 0.18, color=color)
    elif kind == "fedora":
        p.oval(cx - s * 0.8, cy - s * 0.8, cx + s * 0.8, cy + s * 0.8, outline=color, width=w)
        p.arc(cx - s * 0.4, cy - s * 0.4, cx + s * 0.1, cy + s * 0.4, 45, 270, color, width=w)
        p.line([cx - s * 0.35, cy, cx + s * 0.25, cy], color, width=w)
    elif kind == "opensuse":
        p.oval(cx - s * 0.8, cy - s * 0.6, cx + s * 0.8, cy + s * 0.6, outline=color, width=w)
        p.oval(cx - s * 0.2, cy - s * 0.2, cx + s * 0.2, cy + s * 0.2, color=color)
    elif kind == "linux":
        p.oval(cx - s * 0.5, cy - s * 0.8, cx + s * 0.5, cy + s * 0.8, outline=color, width=w)
        p.oval(cx - s * 0.25, cy - s * 0.4, cx + s * 0.25, cy, color=color)
        p.oval(cx - s * 0.15, cy - s * 0.65, cx - s * 0.05, cy - s * 0.55, color=color)
        p.oval(cx + s * 0.05, cy - s * 0.65, cx + s * 0.15, cy - s * 0.55, color=color)
        p.polygon([cx - s * 0.1, cy - s * 0.5, cx + s * 0.1, cy - s * 0.5, cx, cy - s * 0.4], color=WARNING)
    elif kind == "bolt":
        p.polygon([
            cx + s * 0.15, cy - s, cx - s * 0.65, cy + s * 0.1, cx - s * 0.05, cy + s * 0.1,
            cx - s * 0.15, cy + s, cx + s * 0.65, cy - s * 0.1, cx + s * 0.05, cy - s * 0.1,
        ], color)
    elif kind == "link":
        rx, ry, offset = s * 0.55, s * 0.4, s * 0.32
        ring_w = max(2.0, s * 0.24)
        p.oval(cx - offset - rx, cy - ry, cx - offset + rx, cy + ry, outline=color, width=ring_w)
        p.oval(cx + offset - rx, cy - ry, cx + offset + rx, cy + ry, outline=color, width=ring_w)
    elif kind == "trash":
        top, bottom = cy - s * 0.55, cy + s * 0.95
        top_half, bottom_half = s * 0.62, s * 0.5
        p.polygon([cx - top_half, top, cx + top_half, top, cx + bottom_half, bottom, cx - bottom_half, bottom],
                   outline=color, width=w)
        p.line([cx - s * 0.85, top, cx + s * 0.85, top], color, width=w)
        p.line([cx - s * 0.28, top, cx - s * 0.28, top - s * 0.28], color, width=w)
        p.line([cx + s * 0.28, top, cx + s * 0.28, top - s * 0.28], color, width=w)
        p.line([cx - s * 0.28, top - s * 0.28, cx + s * 0.28, top - s * 0.28], color, width=w)
        rib_w = max(1.4, s * 0.1)
        for fx in (-0.26, 0, 0.26):
            p.line([cx + fx * s, top + s * 0.2, cx + fx * s * 0.85, bottom - s * 0.12], color, width=rib_w)
    elif kind == "install":
        p.line([cx - s, cy + s * 0.15, cx - s, cy + s], color, width=w)
        p.line([cx - s, cy + s, cx + s, cy + s], color, width=w)
        p.line([cx + s, cy + s * 0.15, cx + s, cy + s], color, width=w)
        p.line([cx - s * 0.55, cy - s * 0.15, cx - s * 0.05, cy + s * 0.35, cx + s * 0.7, cy - s * 0.55],
               color, width=max(2.0, s * 0.2))
    elif kind == "folder":
        p.polygon([
            cx - s, cy - s * 0.35, cx - s * 0.32, cy - s * 0.35, cx - s * 0.15, cy - s * 0.15,
            cx + s, cy - s * 0.15, cx + s, cy + s * 0.55, cx - s, cy + s * 0.55,
        ], color)
    elif kind == "undo":
        p.arc(cx - s * 0.8, cy - s * 0.75, cx + s * 0.8, cy + s * 0.75, 200, 250, color, width=w)
        p.polygon([cx - s * 0.9, cy - s * 0.1, cx - s * 0.32, cy - s * 0.52, cx - s * 0.42, cy + s * 0.08], color)
    elif kind == "warn":
        p.polygon([cx, cy - s, cx - s, cy + s * 0.7, cx + s, cy + s * 0.7], outline=color, width=w)
        p.line([cx, cy - s * 0.15, cx, cy + s * 0.28], color, width=w)
        p.oval(cx - 1.4, cy + s * 0.42, cx + 1.4, cy + s * 0.5, color)
    elif kind == "info":
        p.oval(cx - s * 0.85, cy - s * 0.85, cx + s * 0.85, cy + s * 0.85, outline=color, width=w)
        p.line([cx, cy - s * 0.05, cx, cy + s * 0.55], color, width=w)
        p.oval(cx - 1.2, cy - s * 0.55, cx + 1.2, cy - s * 0.3, color)
    elif kind == "check":
        p.line([cx - s * 0.7, cy, cx - s * 0.1, cy + s * 0.6, cx + s * 0.8, cy - s * 0.6], color,
               width=max(2.0, s * 0.22))
    elif kind == "x":
        w2 = max(1.8, s * 0.2)
        p.line([cx - s * 0.6, cy - s * 0.6, cx + s * 0.6, cy + s * 0.6], color, width=w2)
        p.line([cx - s * 0.6, cy + s * 0.6, cx + s * 0.6, cy - s * 0.6], color, width=w2)
    elif kind == "refresh":
        p.arc(cx - s * 0.8, cy - s * 0.8, cx + s * 0.8, cy + s * 0.8, 30, 260, color, width=w)
        p.polygon([cx + s * 0.55, cy - s * 0.85, cx + s * 0.95, cy - s * 0.35, cx + s * 0.4, cy - s * 0.25],
                   color)
    elif kind == "spinner":
        start = (frame * 30) % 360
        p.arc(cx - s, cy - s, cx + s, cy + s, start, 110, color, width=w)
    elif kind == "box":
        p.rect(cx - s, cy - s * 0.55, cx + s, cy + s, outline=color, width=w, radius=s * 0.12)
        p.line([cx - s, cy - s * 0.05, cx + s, cy - s * 0.05], color, width=w)
        p.line([cx, cy - s * 0.55, cx, cy + s], color, width=w)

_ICON_PHOTO_CACHE: dict = {}

def render_icon_photo(kind, color, size=20, frame=0):
    if not _PIL_OK:
        return None
    key = (kind, color, size, frame)
    cached = _ICON_PHOTO_CACHE.get(key)
    if cached is not None:
        return cached
    big = size * 4
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _paint_icon(_Painter(draw, pil=True), big / 2, big / 2, kind, color, big * 0.36, frame)
    photo = ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))
    _ICON_PHOTO_CACHE[key] = photo
    return photo

def render_ctk_image(kind, color, size=18, frame=0):
    if not _PIL_OK:
        return None
    from ..compat import ctk
    big = size * 4
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _paint_icon(_Painter(draw, pil=True), big / 2, big / 2, kind, color, big * 0.36, frame)
    resized_img = img.resize((size, size), Image.LANCZOS)
    return ctk.CTkImage(light_image=resized_img, dark_image=resized_img, size=(size, size))

def draw_icon(canvas, cx, cy, kind, color=TEXT, s=7, frame=0):
    _paint_icon(_Painter(canvas, pil=False), cx, cy, kind, color, s, frame)

def blit_icon(canvas, cx, cy, kind, color=TEXT, size=20, frame=0):
    photo = render_icon_photo(kind, color, size, frame)
    if photo is not None:
        canvas.create_image(cx, cy, image=photo)
    else:
        draw_icon(canvas, cx, cy, kind, color=color, s=size * 0.42, frame=frame)

def icon_canvas(parent, kind, color=TEXT, size=20, bg=None):
    c = tk.Canvas(parent, width=size, height=size, highlightthickness=0, bd=0, bg=bg or parent["bg"])
    blit_icon(c, size / 2, size / 2, kind, color=color, size=size)
    return c
