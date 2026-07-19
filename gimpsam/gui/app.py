"""GimpSamApp — root-window plumbing shared by every screen: theming, the
status bar, the background-job runner, the log pump and global keyboard
shortcuts. The screens themselves live in pages/ as mixins; this class
just composes them (landing / sam setup / install-progress). Same design
as LazyGimp's LazyGimpApp, restricted to the SAM domain.
"""
from __future__ import annotations

import queue
import threading

from ..compat import tk
from ..hardware import detect_hardware
from ..job import Job
from ..plan import InstallPlan, PlannedAction
from ..gimp_dirs import is_gimp_installed
from . import theme
from .dialogs import themed_info
from .icons import blit_icon
from .pages import InstallProgressPage, LandingPage, SamPage
from .theme import ACCENT, BG, F_SMALL, TEXT_MUTED


class GimpSamApp(LandingPage, SamPage, InstallProgressPage):
    def __init__(self, root):
        self.root = root
        root.title("GIMPSAM installer")
        root.geometry("1040x800")
        root.minsize(920, 660)
        theme.apply_style(root)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.busy = False
        self.current_job = None
        self.current_screen = "landing"
        self.hw = detect_hardware()

        self.plan = InstallPlan()
        self.plan_actions: list[PlannedAction] = []
        self._exec_log_lines: list[str] = []

        self.root_frame = tk.Frame(root, bg=BG)
        self.root_frame.pack(fill="both", expand=True)
        self.root.bind("<Key>", self._on_global_key)
        if not is_gimp_installed():
            self.show_gimp_missing()
        else:
            self.show_landing()
        self.root.after(150, self._drain_log_queue)

    # ---- status bar -----------------------------------------------------

    def _build_status_bar(self, parent):
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x", padx=26, pady=(0, 14), side="bottom")
        self.status_spinner = tk.Canvas(bar, width=16, height=16, highlightthickness=0, bd=0, bg=BG)
        self.status_spinner.pack(side="left", padx=(0, 8))
        self.status_var = tk.StringVar(value="Full log is also printed to the terminal this was launched from.")
        tk.Label(bar, textvariable=self.status_var, bg=BG, fg=TEXT_MUTED, font=F_SMALL, anchor="w").pack(
            side="left", fill="x", expand=True)
        self._status_spin_frame = 0
        self._status_spinning = False

    def _spin_status(self):
        if not self._status_spinning or not self.status_spinner.winfo_exists():
            return
        self.status_spinner.delete("all")
        blit_icon(self.status_spinner, 8, 8, "spinner", color=ACCENT, size=16, frame=self._status_spin_frame % 12)
        self._status_spin_frame += 1
        self.root.after(90, self._spin_status)

    # ---- log pump --------------------------------------------------------

    _STATUS_MAX_CHARS = 160

    def _drain_log_queue(self):
        msgs = []
        try:
            while True:
                msgs.append(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        if msgs:
            last = msgs[-1]
            if hasattr(self, "status_var") and self.status_var is not None:
                clean = " ".join(last.replace("\r", " ").split())
                if len(clean) > self._STATUS_MAX_CHARS:
                    clean = "…" + clean[-(self._STATUS_MAX_CHARS - 1):]
                try:
                    self.status_var.set(clean)
                except tk.TclError:
                    pass
            if self.current_screen == "installing":
                self._exec_log_lines.extend(msgs)
                del self._exec_log_lines[:-500]
                # One batched Text insert per tick, however many lines
                # arrived — pip can emit hundreds of lines a second and a
                # per-line insert+scroll would stall the main thread.
                self._append_exec_log_lines(msgs)
        self.root.after(150, self._drain_log_queue)

    # ---- background jobs -------------------------------------------------

    def set_busy(self, busy: bool):
        self.busy = busy
        if not hasattr(self, "status_spinner") or not self.status_spinner.winfo_exists():
            return
        self._status_spinning = busy
        if busy:
            self._spin_status()
        else:
            self.status_spinner.delete("all")

    def run_in_background(self, fn, on_done=None):
        if self.busy:
            themed_info(self.root, "Busy", "Another operation is already running.")
            return
        self.set_busy(True)
        job = Job(self.log_queue)
        self.current_job = job

        def wrapper():
            try:
                fn(job)
            except Exception as e:
                job.log(f"ERROR: {e}")
            finally:
                if self.current_job is job:
                    self.current_job = None
                self.root.after(0, lambda: (self.set_busy(False), (on_done() if on_done else None)))

        threading.Thread(target=wrapper, daemon=True).start()

    def cancel_current_job(self):
        if self.current_job is not None:
            self.current_job.log("Cancel requested by user — stopping...")
            self.current_job.cancel()

    # ---- global keyboard shortcuts ---------------------------------------

    def _on_global_key(self, event):
        focused = self.root.focus_get()
        if focused:
            try:
                widget_class = str(focused.winfo_class())
                if "entry" in widget_class.lower() or "text" in widget_class.lower():
                    return
            except Exception:
                pass

        key = event.keysym.lower()

        if self.current_screen == "landing":
            if key in ("1", "s"):
                self.show_sam_setup()
            elif key in ("2", "q"):
                self.start_quick_setup()

        elif self.current_screen == "sam":
            if key in ("left", "escape", "backspace"):
                self._sam_back()
            elif key in ("return", "space"):
                self._sam_start_install()
            elif key == "t":
                entry = getattr(self, "_hf_token_entry", None)
                if entry and entry.winfo_exists():
                    entry.focus_set()
            elif key == "p":
                combo = getattr(self, "_pytorch_combo", None)
                if combo and combo.winfo_exists():
                    combo.focus_set()
                    try:
                        combo._clicked()
                    except Exception:
                        pass
            elif key in ("a", "b", "h", "1", "2", "3", "4", "5"):
                handler = getattr(self, "_sam_cards", {}).get({
                    "a": "queue_all_sam1", "b": "queue_all_sam2", "h": "sam3",
                    "1": "sam_model:sam_vit_b", "2": "sam_model:sam_vit_l",
                    "3": "sam_model:sam_vit_h", "4": "sam_model:sam2_hiera_tiny",
                    "5": "sam3",
                }.get(key, ""))
                if handler:
                    handler()
