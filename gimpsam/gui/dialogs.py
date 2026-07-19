"""Themed modal dialogs, the snackbar and the sudo password prompt."""

from __future__ import annotations

from ..compat import ctk, tk
from .helpers import autowrap_label
from .icons import icon_canvas
from .theme import BG, CARD_BG, F_BODY, F_BODY_B, F_DIALOG_TITLE, TEXT, TEXT_MUTED, TONE_COLORS
from .widgets import RoundedButton, RoundedCard
import threading


def themed_dialog(root, title, message, kind="info"):
    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg=CARD_BG)
    win.transient(root)
    card = RoundedCard(win, radius=18, pad=20, width=380)
    card.pack(padx=0, pady=0)
    tk.Label(card.body, text=title, bg=CARD_BG, fg=TEXT, font=F_DIALOG_TITLE).pack(anchor="w")
    autowrap_label(card.body, message, fg=TEXT_MUTED, bg=CARD_BG, font=F_BODY).pack(
        anchor="w", fill="x", pady=(10, 18))
    result = {"value": None}
    btns = tk.Frame(card.body, bg=CARD_BG)
    btns.pack(anchor="e")

    def close(v):
        result["value"] = v
        win.destroy()

    if kind == "confirm":
        RoundedButton(btns, "Cancel", variant="secondary", width=90, command=lambda: close(False)).pack(
            side="left", padx=(0, 8))
        RoundedButton(btns, "Confirm", variant="danger", icon="trash", width=120,
                      command=lambda: close(True)).pack(side="left")
    else:
        RoundedButton(btns, "OK", variant="primary", width=90, command=lambda: close(True)).pack(side="left")
        
    win.bind("<Escape>", lambda _e: close(False if kind == "confirm" else True))
    win.bind("<Return>", lambda _e: close(True))
    
    card.finalize()
    win.update_idletasks()
    rx, ry, rw, rh = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
    ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
    win.geometry(f"+{rx + max(0, (rw - ww) // 2)}+{ry + max(0, (rh - wh) // 2)}")
    win.focus_force()
    win.grab_set()
    win.wait_window()
    return result["value"]

def themed_info(root, title, message):
    themed_dialog(root, title, message, kind="info")

def themed_confirm(root, title, message) -> bool:
    return bool(themed_dialog(root, title, message, kind="confirm"))

def show_snackbar(app, message: str, tone: str = "warn", duration_ms: int = 2200):
    bgc, fg = TONE_COLORS.get(tone, TONE_COLORS["warn"])
    root = app.root
    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg=BG)
    card = RoundedCard(win, bg=bgc, border=bgc, radius=14, pad=14)
    card.pack()
    row = tk.Frame(card.body, bg=bgc)
    row.pack()
    icon_canvas(row, "warn" if tone == "warn" else ("x" if tone == "error" else "check"), color=fg, size=18,
                bg=bgc).pack(side="left", padx=(0, 8))
    tk.Label(row, text=message, bg=bgc, fg=fg, font=F_BODY_B).pack(side="left")
    card.finalize()
    win.update_idletasks()
    x = root.winfo_rootx() + max(0, (root.winfo_width() - win.winfo_reqwidth()) // 2)
    y = root.winfo_rooty() + root.winfo_height() - 110
    win.geometry(f"+{x}+{y}")
    win.after(duration_ms, lambda: win.destroy() if win.winfo_exists() else None)

class TkPasswordPrompt:
    """Themed modal password prompt for the sudo install path. Called from
    the worker thread; the dialog itself runs on the Tk main loop."""

    def __init__(self, root):
        self.root = root

    def __call__(self, prompt_text: str) -> str:
        result: dict = {}
        done = threading.Event()

        def ask():
            try:
                result["pw"] = self._show(prompt_text)
            finally:
                done.set()

        self.root.after(0, ask)
        done.wait()
        return result.get("pw") or ""

    def _show(self, prompt_text: str) -> str:
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=CARD_BG)
        win.transient(self.root)
        card = RoundedCard(win, radius=18, pad=20, width=420)
        card.pack(padx=0, pady=0)
        tk.Label(card.body, text="Administrator password", bg=CARD_BG, fg=TEXT,
                 font=F_DIALOG_TITLE).pack(anchor="w")
        autowrap_label(
            card.body,
            f"{prompt_text}\n\nNeeded to install/remove system packages — your normal login "
            "password, sent straight to sudo, never stored.",
            fg=TEXT_MUTED, bg=CARD_BG, font=F_BODY,
        ).pack(anchor="w", fill="x", pady=(10, 14))
        pw_var = tk.StringVar()
        entry = ctk.CTkEntry(card.body, textvariable=pw_var, show="•", width=360)
        entry.pack(anchor="w", pady=(0, 16))
        result = {"pw": ""}
        btns = tk.Frame(card.body, bg=CARD_BG)
        btns.pack(anchor="e")

        def close(ok: bool):
            result["pw"] = pw_var.get() if ok else ""
            win.destroy()

        RoundedButton(btns, "Cancel", variant="secondary", width=90,
                      command=lambda: close(False)).pack(side="left", padx=(0, 8))
        RoundedButton(btns, "Unlock", variant="primary", width=110,
                      command=lambda: close(True)).pack(side="left")
        win.bind("<Return>", lambda _e: close(True))
        win.bind("<Escape>", lambda _e: close(False))
        card.finalize()
        win.update_idletasks()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{rx + max(0, (rw - ww) // 2)}+{ry + max(0, (rh - wh) // 2)}")
        entry.focus_set()
        win.focus_force()
        win.grab_set()
        win.wait_window()
        return result["pw"]
