"""Landing screen + Quick Setup (a prefilled plan handed to the shared
install-progress executor) + full removal."""

from __future__ import annotations

from ...backend import backend_ready, bridge_self_test, install_sam_backend, remove_sam_backend, write_sam_info
from ...hardware import recommended_model_key, recommended_torch_index
from ...job import Job
from ...models import MODEL_BY_KEY, any_model_installed, model_path
from ...plan import PlannedAction
from ...plugin import install_plugin, plugin_installed, remove_plugin, write_plugin_settings
from ..dialogs import themed_confirm, themed_info
from ..helpers import autowrap_label
from ..icons import icon_canvas
from ..state import anything_installed, status_lines
from ..theme import BG, CARD_BG, F_BODY, F_CARD_TITLE, F_HERO, F_SMALL, F_SUBTITLE, SUCCESS, TEXT, TEXT_MUTED
from ..widgets import ModernCheckbox, RoundedButton, RoundedCard, bind_click_recursive
from ...compat import tk
import os
import sys


class LandingPage:
    def show_landing(self):
        self.current_screen = "landing"
        for w in self.root_frame.winfo_children():
            w.destroy()

        wrap = tk.Frame(self.root_frame, bg=BG)
        wrap.pack(fill="both", expand=True)
        self._build_status_bar(wrap)
        center = tk.Frame(wrap, bg=BG)
        center.place(relx=0.5, rely=0.42, anchor="center")

        tk.Label(center, text="GIMPSAM", bg=BG, fg=TEXT, font=F_HERO).pack()
        tk.Label(center, text="Segment Anything for GIMP — plug-in, Python backend and models",
                 bg=BG, fg=TEXT_MUTED, font=F_SUBTITLE).pack(pady=(2, 14))

        status = tk.Frame(center, bg=BG)
        status.pack(pady=(0, 20))
        for ok, text in status_lines():
            row = tk.Frame(status, bg=BG)
            row.pack(anchor="w", pady=1)
            icon_canvas(row, "check" if ok else "circle", color=SUCCESS if ok else TEXT_MUTED,
                        size=16, bg=BG).pack(side="left", padx=(0, 8))
            tk.Label(row, text=text, bg=BG, fg=TEXT if ok else TEXT_MUTED, font=F_BODY).pack(side="left")

        row = tk.Frame(center, bg=BG)
        row.pack()
        CARD_W, CARD_H = 320, 245

        manage = RoundedCard(row, radius=20, pad=24, width=CARD_W, height=CARD_H)
        manage.grid(row=0, column=0, padx=10)
        title_row = tk.Frame(manage.body, bg=CARD_BG)
        title_row.pack(anchor="w")
        icon_canvas(title_row, "gear", color=TEXT, size=22).pack(side="left", padx=(0, 8))
        tk.Label(title_row, text="Custom setup", bg=CARD_BG, fg=TEXT, font=F_CARD_TITLE).pack(side="left")
        autowrap_label(
            manage.body,
            "Pick the PyTorch build and exactly which SAM models to download (or remove), "
            "then run the whole checklist in one pass.",
            bg=CARD_BG, font=F_SMALL,
        ).pack(anchor="w", fill="x", pady=(8, 16))
        open_btn = RoundedButton(manage.body, "Open (1)", variant="secondary", width=272, height=40,
                                  font=F_ITEM_TITLE, command=self.show_sam_setup)
        open_btn.pack(anchor="w", side="bottom")
        manage.finalize()
        bind_click_recursive(manage, self.show_sam_setup, skip=(open_btn,))

        auto = RoundedCard(row, radius=20, pad=24, width=CARD_W, height=CARD_H)
        auto.grid(row=0, column=1, padx=10)
        title_row2 = tk.Frame(auto.body, bg=CARD_BG)
        title_row2.pack(anchor="w")
        icon_canvas(title_row2, "bolt", color=TEXT, size=22).pack(side="left", padx=(0, 8))
        tk.Label(title_row2, text="Quick setup", bg=CARD_BG, fg=TEXT, font=F_CARD_TITLE).pack(side="left")
        autowrap_label(
            auto.body,
            "Installs everything still missing: the GIMP plug-in, the Python backend (PyTorch matched "
            "to your hardware) and a recommended model. Already-installed pieces are left alone.",
            bg=CARD_BG, font=F_SMALL,
        ).pack(anchor="w", fill="x", pady=(8, 16))
        start_btn = RoundedButton(auto.body, "Start (2)", variant="primary", width=272, height=40,
                                   font=F_ITEM_TITLE, command=self.start_quick_setup)
        start_btn.pack(anchor="w", side="bottom")
        auto.finalize()
        bind_click_recursive(auto, self.start_quick_setup, skip=(start_btn,))

        if anything_installed():
            btn_row = tk.Frame(center, bg=BG)
            btn_row.pack(pady=(24, 0))
            RoundedButton(btn_row, "Remove everything from this system", variant="danger", icon="trash",
                          width=400, height=46, command=self._confirm_remove_all).pack()

        # The installer is disposable by design: this drives the same
        # --ephemeral self-destruction (binary, .pyz or source folder) via
        # the env flag util._self_destruct_if_ephemeral() checks on exit.
        self._ephemeral_var = tk.BooleanVar(
            value="--ephemeral" in sys.argv or os.environ.get("GIMPSAM_INSTALLER_EPHEMERAL") == "1")

        def sync_ephemeral():
            os.environ["GIMPSAM_INSTALLER_EPHEMERAL"] = "1" if self._ephemeral_var.get() else "0"

        ModernCheckbox(center, self._ephemeral_var, command=sync_ephemeral,
                       text="Delete this installer when it closes — leaves the folder clean",
                       font=F_SUBTITLE,
                       ).pack(pady=(26, 0))
        sync_ephemeral()

    # ---- quick setup: everything missing, in priority order -----------

    def start_quick_setup(self):
        if self.busy:
            themed_info(self.root, "Busy", "Setup is already running.")
            return
        # One-click setup is just a prefilled plan handed straight to the
        # same executor the setup page uses — no separate code path.
        self.show_install_progress(self._build_quick_setup_plan())

    def _build_quick_setup_plan(self) -> list["PlannedAction"]:
        actions: list[PlannedAction] = []

        if not plugin_installed():
            actions.append(PlannedAction("plugin:install", "Install the GIMP plug-in", "install",
                                          lambda job: install_plugin(job)))

        if not backend_ready():
            actions.append(PlannedAction(
                "backend:install", "Set up the Python backend", "install",
                lambda job: install_sam_backend(job, recommended_torch_index(self.hw))))

        if not any_model_installed():
            rec = MODEL_BY_KEY[recommended_model_key(self.hw)]

            def install_recommended(job: Job, rec=rec):
                if job.download(rec.url, model_path(rec), job.cancel_event):
                    write_plugin_settings(rec)
                    write_sam_info([rec.key])
                    bridge_self_test(job, rec)

            actions.append(PlannedAction(f"sam_model:{rec.key}:install",
                                          f"Download the recommended SAM model: {rec.label}",
                                          "install", install_recommended))

        return actions

    # ---- full removal --------------------------------------------------

    def _confirm_remove_all(self):
        if not themed_confirm(self.root, "Remove everything",
                              "Remove the GIMP plug-in, the Python backend and every downloaded "
                              "model from this system?"):
            return

        def run(job: Job):
            remove_plugin(job)
            remove_sam_backend(job)

        self.show_install_progress([PlannedAction("remove_all", "Remove GIMPSAM completely", "remove", run)])

    def show_gimp_missing(self):
        self.current_screen = "gimp_missing"
        for w in self.root_frame.winfo_children():
            w.destroy()

        wrap = tk.Frame(self.root_frame, bg=BG)
        wrap.pack(fill="both", expand=True)
        center = tk.Frame(wrap, bg=BG)
        center.place(relx=0.5, rely=0.45, anchor="center")

        icon_canvas(center, "warn", color=TEXT, size=64, bg=BG).pack(pady=(0, 16))

        tk.Label(center, text="GIMP is not installed", bg=BG, fg=TEXT, font=F_HERO).pack()
        tk.Label(
            center,
            text="GIMPSAM requires a working GIMP installation on your system to manage its plug-ins.\n\n"
                 "Please install GIMP first using your system's package manager (e.g., via pacman or apt) "
                 "or download the official GIMP AppImage into your Applications folder.\n\n"
                 "Once GIMP is installed, please restart this installer.",
            bg=BG, fg=TEXT_MUTED, font=F_BODY, justify="center", wraplength=600
        ).pack(fill="x", pady=(14, 24))

        exit_btn = RoundedButton(center, "Exit Installer", variant="primary", width=220, height=40,
                                 command=self.root.destroy)
        exit_btn.pack()
