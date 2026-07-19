"""Shared install-progress screen: runs a list[PlannedAction]
sequentially in one background thread, with live progress + log."""

from __future__ import annotations

from ...compat import ctk, tk
from ...job import Job
from ...plan import PlannedAction
from ..theme import BG, CARD_BORDER, F_BODY, F_H2, F_MONO, LOG_BG, TEXT, TEXT_MUTED
from ..widgets import ProgressBar, RoundedButton


class InstallProgressPage:
    def show_install_progress(self, actions: list[PlannedAction]):
        self.plan_actions = list(actions)
        self.exec_total = len(self.plan_actions)
        self.exec_done = 0
        self.exec_cancelled = False
        self.exec_finished = False
        self._exec_log_lines = []
        self._render_install_progress()
        self._run_plan()

    def _exec_progress_text(self) -> str:
        if self.exec_total == 0:
            return "Nothing was queued."
        if self.exec_finished:
            if self.exec_cancelled:
                return f"Stopped after {self.exec_done} of {self.exec_total} steps."
            return f"Finished {self.exec_done} of {self.exec_total} steps."
        return f"Step {min(self.exec_done + 1, self.exec_total)} of {self.exec_total}"

    def _render_install_progress(self):
        self.current_screen = "installing"
        for w in self.root_frame.winfo_children():
            w.destroy()

        content = tk.Frame(self.root_frame, bg=BG)
        content.pack(fill="both", expand=True, padx=32, pady=24)

        title = "Installation finished" if self.exec_finished else "Installing…"
        tk.Label(content, text=title, bg=BG, fg=TEXT, font=F_H2).pack(anchor="w")

        self.exec_step_lbl = tk.Label(content, text=self._exec_progress_text(), bg=BG, fg=TEXT_MUTED,
                                       font=F_BODY)
        self.exec_step_lbl.pack(anchor="w", pady=(4, 10))

        self.exec_progress_bar = ProgressBar(content, width=760, height=10)
        self.exec_progress_bar.pack(anchor="w", fill="x")
        self.exec_progress_bar.set_fraction(self.exec_done / self.exec_total if self.exec_total else 1.0)

        # A RoundedCard sizes itself to its content's *requested* height,
        # which would cap this panel at a fixed number of text lines no
        # matter how much room the window actually has — so the log gets
        # a plain bordered Frame instead, which correctly stretches to
        # fill whatever vertical space is left (fill="both", expand=True
        # all the way down this chain).
        self.exec_log_text = ctk.CTkTextbox(content, fg_color=LOG_BG, text_color=TEXT,
                                            corner_radius=12, border_width=1,
                                            border_color=CARD_BORDER, wrap="word",
                                            font=F_MONO, state="disabled")
        self.exec_log_text.pack(fill="both", expand=True, pady=(16, 0))
        self._append_exec_log_lines(self._exec_log_lines)

        btn_row = tk.Frame(content, bg=BG)
        btn_row.pack(fill="x", pady=(16, 0))
        if self.exec_finished:
            RoundedButton(btn_row, "Done", variant="primary", width=140,
                          command=self.show_landing).pack(side="left")
        else:
            RoundedButton(btn_row, "Stop", icon="x", variant="danger", width=140,
                          command=self._stop_plan_execution).pack(side="left")

    def _append_exec_log_lines(self, lines: list[str]):
        """One insert + one scroll per batch (the log pump hands us every
        line that arrived in the last tick at once), and the Text widget is
        trimmed to the same 500-line window as the replay buffer — pip can
        emit hundreds of lines a second without stalling the main thread."""
        if not lines or not hasattr(self, "exec_log_text") or not self.exec_log_text.winfo_exists():
            return
        text = self.exec_log_text
        text.configure(state="normal")
        text.insert("end", "\n".join(lines) + "\n")
        overflow = int(text.index("end-1c").split(".")[0]) - 500
        if overflow > 0:
            text.delete("1.0", f"{overflow + 1}.0")
        text.see("end")
        text.configure(state="disabled")

    def _bump_exec_progress(self):
        if hasattr(self, "exec_step_lbl") and self.exec_step_lbl.winfo_exists():
            self.exec_step_lbl.configure(text=self._exec_progress_text())
        if hasattr(self, "exec_progress_bar") and self.exec_progress_bar.winfo_exists():
            self.exec_progress_bar.set_fraction(self.exec_done / self.exec_total if self.exec_total else 1.0)

    def _run_plan(self):
        actions = self.plan_actions

        def task(job: Job):
            for action in actions:
                if job.cancel_event.is_set():
                    self.exec_cancelled = True
                    job.log(f"Stopped before: {action.label}")
                    break
                job.log(f"→ {action.label}")
                try:
                    action.run(job)
                except Exception as e:
                    job.log(f"ERROR during {action.label}: {e}")
                self.exec_done += 1
                self.root.after(0, self._bump_exec_progress)
            if not actions:
                job.log("Nothing was queued.")
            elif self.exec_cancelled:
                job.log("Stopped — whatever finished so far was left in place.")
            else:
                job.log("All done! Restart GIMP to see everything.")

        self.run_in_background(task, on_done=self._finish_plan)

    def _stop_plan_execution(self):
        self.cancel_current_job()

    def _finish_plan(self):
        self.exec_finished = True
        self._render_install_progress()
