"""Reusable widgets — CustomTkinter engine behind the SAME API the pages
already use (RoundedButton, RoundedCard, ProgressBar, ModernCheckbox,
ScrollableFrame). The pages didn't have to change when the engine did:
that's the point of the facade.

Plain tk.Label/tk.Frame children keep working inside these widgets as
long as their bg matches the card color — the theme guarantees it.
"""
from __future__ import annotations

from ..compat import ctk, tk
from .helpers import autowrap_label
from .icons import icon_canvas
from .theme import (
    ACCENT, ACCENT_HOVER, ACCENT_TEXT, BG, CARD_BG, CARD_BORDER, DANGER, DANGER_HOVER,
    DANGER_TEXT, DISABLED_BG, DISABLED_TEXT, F_BODY, F_BODY_B, F_H2, F_SMALL, SECONDARY_HOVER,
    SUCCESS, SUCCESS_HOVER, SUCCESS_TEXT, TEXT, TEXT_MUTED, TONE_COLORS,
)

# Text glyphs standing in for the old vector icons inside buttons — safe
# in DejaVu Sans (the default Linux UI font), no emoji fonts involved.
_BUTTON_GLYPHS = {
    "install": "↓", "trash": "✕", "bolt": "⚡", "refresh": "⟳",
    "link": "↗", "x": "✕", "box": "▣", "check": "✓",
}


class RoundedButton(ctk.CTkButton):
    _PALETTE = {
        "primary": (ACCENT, ACCENT_HOVER, ACCENT_TEXT),
        "success": (SUCCESS, SUCCESS_HOVER, SUCCESS_TEXT),
        "danger": (DANGER, DANGER_HOVER, DANGER_TEXT),
        "secondary": (CARD_BORDER, SECONDARY_HOVER, TEXT),
    }

    def __init__(self, parent, text, command=None, variant="secondary", icon=None,
                 width=None, height=34, radius=13, font=F_BODY_B, bg=None, on_blocked=None):
        fill, hover, fg = self._PALETTE[variant]
        self.icon_name = icon
        self._icon_image = None
        if icon:
            from .icons import render_ctk_image
            self._icon_image = render_ctk_image(icon, fg, size=18)
        if self._icon_image:
            self._icon_glyph = ""
        else:
            self._icon_glyph = _BUTTON_GLYPHS.get(icon, "") if icon else ""
        self._base_text = text
        self.on_blocked = on_blocked
        self.variant = variant
        self._loading = False
        self._loading_base = ""
        self._loading_frame = 0
        super().__init__(
            parent, text=self._decorated(text), command=command,
            width=width or 140, height=height, corner_radius=radius,
            fg_color=fill, hover_color=hover, text_color=fg,
            text_color_disabled=DISABLED_TEXT, font=font, border_width=0,
            image=self._icon_image
        )
        # Clicking a disabled button still means something on some pages
        # (e.g. "enter a HF token first") — CTk swallows the click, so we
        # listen underneath.
        if on_blocked is not None:
            self.bind("<Button-1>", self._maybe_blocked)

    # -- old-API surface -------------------------------------------------

    @property
    def command(self):
        return self._command

    @command.setter
    def command(self, fn):
        self._command = fn

    @property
    def text(self):
        return self._base_text

    def set_text(self, text: str):
        self._base_text = text
        if not self._loading:
            self.configure(text=self._decorated(text))

    def set_enabled(self, enabled: bool):
        self.configure(state="normal" if enabled else "disabled")
        # keep the fill readable when disabled (CTk only dims the text)
        fill = self._PALETTE[self.variant][0] if enabled else DISABLED_BG
        self.configure(fg_color=fill)

    def set_variant(self, variant: str):
        self.variant = variant
        fill, hover, fg = self._PALETTE[variant]
        self.configure(fg_color=fill, hover_color=hover, text_color=fg)
        if self.icon_name:
            from .icons import render_ctk_image
            self._icon_image = render_ctk_image(self.icon_name, fg, size=18)
            if self._icon_image:
                self.configure(image=self._icon_image)

    def start_loading(self, base_text="Working"):
        if self._loading:
            return
        self._loading = True
        self._loading_base = base_text
        self.configure(state="disabled")
        self._animate()

    def stop_loading(self):
        self._loading = False
        self.configure(state="normal", text=self._decorated(self._base_text))

    # -- internals ---------------------------------------------------------

    def _decorated(self, text: str) -> str:
        return f"{self._icon_glyph}  {text}" if self._icon_glyph and text else (self._icon_glyph or text)

    def _maybe_blocked(self, _event=None):
        if self.cget("state") == "disabled" and self.on_blocked:
            self.on_blocked()

    def _animate(self):
        if not self._loading or not self.winfo_exists():
            return
        dots = "." * (1 + self._loading_frame % 3)
        self.configure(text=f"{self._loading_base}{dots}")
        self._loading_frame += 1
        self.after(350, self._animate)


class RoundedCard(ctk.CTkFrame):
    """A rounded card with a `.body` plain-tk frame for content — pages
    pack tk.Label/tk.Frame children into .body exactly as before.
    Supports optional interactivity (hovering, clicking, active border color/width).
    """

    def __init__(self, parent, bg=CARD_BG, border=CARD_BORDER, radius=18, pad=18, width=None, height=None,
                 command=None, hover_bg="#2f323a", hover_border=None, active_border=None, active_width=1):
        super().__init__(parent, fg_color=bg, border_color=border, border_width=active_width if active_border else 1,
                         corner_radius=radius, width=width or 200, height=height or 200)
        if width or height:
            self.pack_propagate(False)
            self.grid_propagate(False)
        self._bg = bg
        self._border = border
        self._command = command
        self._hover_bg = hover_bg
        self._hover_border = hover_border
        self._active_border = active_border
        self._active_width = active_width
        self._hovered = False

        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill="both", expand=True, padx=pad, pady=pad)

    def finalize(self):
        if self._command is not None:
            self._bind_events(self)
            self._update_colors()

    def _bind_events(self, widget):
        if isinstance(widget, (ctk.CTkButton, tk.Button)):
            return
        try:
            widget.configure(cursor="hand2")
        except Exception:
            pass
        widget.bind("<Button-1>", lambda e: self._on_click(), add="+")
        widget.bind("<Enter>", lambda e: self._on_enter(), add="+")
        widget.bind("<Leave>", lambda e: self._on_leave(), add="+")
        for child in widget.winfo_children():
            self._bind_events(child)

    def _on_click(self):
        if self._command:
            self._command()

    def _on_enter(self):
        self._hovered = True
        self._update_colors()

    def _on_leave(self):
        self._hovered = False
        self._update_colors()

    def _update_colors(self):
        bg_color = self._hover_bg if self._hovered else self._bg
        if self._active_border is not None:
            border_color = self._active_border
            border_width = self._active_width
        else:
            border_color = self._hover_border if (self._hovered and self._hover_border) else self._border
            border_width = 1
        self.configure(fg_color=bg_color, border_color=border_color, border_width=border_width)
        self._set_bg_recursive(self.body, bg_color)

    def _set_bg_recursive(self, widget, bg_color):
        if isinstance(widget, (ctk.CTkButton, tk.Button)):
            return
        if not isinstance(widget, ctk.CTkBaseClass):
            try:
                widget.configure(bg=bg_color)
            except Exception:
                pass
        for child in widget.winfo_children():
            self._set_bg_recursive(child, bg_color)


class ProgressBar(ctk.CTkProgressBar):
    def __init__(self, parent, width=200, height=7, bg=None, track=CARD_BORDER, fill=ACCENT):
        super().__init__(parent, width=width, height=height, corner_radius=height // 2,
                         fg_color=track, progress_color=fill, border_width=0)
        self.set(0)

    def set_fraction(self, frac: float):
        self.set(max(0.0, min(1.0, frac)))


class ModernCheckbox(ctk.CTkCheckBox):
    """With `text`, the label is part of the checkbox: clicking it toggles
    and hovering anywhere on the row highlights the box — CTk behavior,
    for free."""

    def __init__(self, parent, variable, command=None, size=22, bg=None,
                 text="", font=None, text_color=None):
        kwargs = {}
        if not text:
            kwargs["width"] = size
        super().__init__(parent, text=text, variable=variable, onvalue=True, offvalue=False,
                         command=command, height=size,
                         checkbox_width=size, checkbox_height=size, corner_radius=6,
                         fg_color=ACCENT, hover_color=ACCENT_HOVER, border_color=CARD_BORDER,
                         border_width=2, checkmark_color=ACCENT_TEXT,
                         font=font or F_BODY, text_color=text_color or TEXT_MUTED,
                         **kwargs)


class ScrollableFrame(ctk.CTkScrollableFrame):
    """CTkScrollableFrame subclasses tkinter.Frame, so plain-tk children
    land inside the scrolled area, and it handles the mouse wheel itself
    (recursively, on enter/leave) — no app-level routing needed."""

    def __init__(self, parent, bg=BG):
        super().__init__(parent, fg_color=bg, corner_radius=0)
        self.inner = self  # old call sites pack content into .inner

    def _mouse_wheel_all(self, event):
        import sys
        if self.check_if_master_is_canvas(event.widget):
            multiplier = 4
            if sys.platform.startswith("win"):
                if self._shift_pressed:
                    if self._parent_canvas.xview() != (0.0, 1.0):
                        self._parent_canvas.xview("scroll", -int(event.delta / 6) * multiplier, "units")
                else:
                    if self._parent_canvas.yview() != (0.0, 1.0):
                        self._parent_canvas.yview("scroll", -int(event.delta / 6) * multiplier, "units")
            elif sys.platform == "darwin":
                if self._shift_pressed:
                    if self._parent_canvas.xview() != (0.0, 1.0):
                        self._parent_canvas.xview("scroll", -event.delta * multiplier, "units")
                else:
                    if self._parent_canvas.yview() != (0.0, 1.0):
                        self._parent_canvas.yview("scroll", -event.delta * multiplier, "units")
            else:
                if self._shift_pressed:
                    if self._parent_canvas.xview() != (0.0, 1.0):
                        self._parent_canvas.xview_scroll(-1 * multiplier if event.num == 4 else 1 * multiplier, "units")
                else:
                    if self._parent_canvas.yview() != (0.0, 1.0):
                        self._parent_canvas.yview_scroll(-1 * multiplier if event.num == 4 else 1 * multiplier, "units")

    def page_up(self):
        try:
            if self._parent_canvas.winfo_exists():
                self._parent_canvas.yview_scroll(-1, "pages")
        except Exception:
            pass

    def page_down(self):
        try:
            if self._parent_canvas.winfo_exists():
                self._parent_canvas.yview_scroll(1, "pages")
        except Exception:
            pass


def bind_click_recursive(widget, handler, skip=()):
    if widget in skip:
        return
    try:
        widget.configure(cursor="hand2")
    except tk.TclError:
        pass
    widget.bind("<Button-1>", lambda e: handler(), add="+")
    for child in widget.winfo_children():
        bind_click_recursive(child, handler, skip)


def page_header(parent, title):
    tk.Label(parent, text=title, bg=BG, fg=TEXT, font=F_H2).pack(anchor="w", pady=(0, 16))


def callout(parent, text, tone="info"):
    icon_kind = {"info": "info", "warn": "warn", "ok": "check"}[tone]
    bgc, fg = TONE_COLORS[tone]
    card = RoundedCard(parent, bg=bgc, border=bgc, radius=14, pad=12)
    card.pack(fill="x", pady=(4, 12))
    row = tk.Frame(card.body, bg=bgc)
    row.pack(fill="x")
    icon_canvas(row, icon_kind, color=fg, size=20, bg=bgc).pack(side="left", padx=(0, 8), anchor="n")
    autowrap_label(row, text, fg=fg, bg=bgc, font=F_SMALL).pack(side="left", fill="x", expand=True)
    card.finalize()
    return card
