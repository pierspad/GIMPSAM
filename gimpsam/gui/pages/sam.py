"""The SAM setup screen — a single-page port of LazyGimp's wizard SAM
page: PyTorch build selector, per-model cards by family, the gated SAM 3.1
card, and a plan/checklist executed by the shared progress screen. Every
click only queues PlannedActions into self.plan; nothing here touches
disk. Toggles refresh widgets in place (never a full-page rebuild), which
is what keeps this page from flashing on every click."""

from __future__ import annotations

from ...backend import (backend_ready, install_sam3_transformers, install_sam_backend,
                        remove_sam_backend, write_sam_info)
from ...compat import ctk, tk
from ...constants import TORCH_INDEX_URLS
from ...hardware import recommended_model_key, recommended_torch_index
from ...job import Job
from ...models import MODEL_BY_KEY, MODEL_REGISTRY, ModelSpec, model_installed, model_path
from ...plan import InstallPlan, PlannedAction
from ...plugin import install_plugin, plugin_installed, remove_plugin, write_plugin_settings
from ...sam3 import download_sam3, remove_sam3, sam3_failure_message
from ...constants import SAM3_HF_PAGE, SAM3_HF_REPO_ID
from ..dialogs import show_snackbar, themed_confirm, themed_info
from ..helpers import autowrap_label, rating_widget
from ..icons import blit_icon, icon_canvas
from ..theme import (ACCENT, BG, CARD_BG, CARD_BORDER, DANGER, F_BODY, F_BODY_B, F_H3,
                     F_ITEM_TITLE, F_SECTION, F_SMALL, F_SMALL_B, FIELD_BG, SECONDARY_HOVER,
                     SUCCESS, TEXT, TEXT_MUTED)
from ..widgets import RoundedButton, RoundedCard, ScrollableFrame
import os
import shutil
import webbrowser


class SamPage:
    def show_sam_setup(self):
        self.current_screen = "sam"
        self.plan = InstallPlan()
        default_choice = list(TORCH_INDEX_URLS.keys())[
            list(TORCH_INDEX_URLS.values()).index(recommended_torch_index(self.hw))]
        self.torch_choice = tk.StringVar(value=default_choice)
        self.hf_token_var = tk.StringVar()
        self._sam_cards = {}

        for w in self.root_frame.winfo_children():
            w.destroy()

        outer = tk.Frame(self.root_frame, bg=BG)
        outer.place(relx=0, rely=0, relwidth=1, relheight=1)

        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x", padx=26, pady=(16, 0), side="top")
        tk.Label(header, text="SAM setup", bg=BG, fg=TEXT, font=F_H3).pack(side="left")
        tk.Label(header, text="Queue actions, then Install", bg=BG, fg=TEXT_MUTED,
                 font=F_BODY).pack(side="right")

        nav = tk.Frame(outer, bg=BG)
        nav.pack(fill="x", padx=26, pady=(10, 16), side="bottom")
        RoundedButton(nav, "← Back [Backspace]", variant="secondary", width=160,
                      command=self._sam_back).pack(side="left")
        self._sam_install_btn = RoundedButton(nav, "Install (0) [Enter]", icon="bolt", variant="primary",
                                              width=220, command=self._sam_start_install)
        self._sam_install_btn.pack(side="right")
        self._sam_install_btn.set_enabled(False)

        self._build_status_bar(outer)

        middle = tk.Frame(outer, bg=BG)
        middle.pack(fill="both", expand=True, side="top")
        scroller = ScrollableFrame(middle)
        scroller.pack(fill="both", expand=True, padx=(26, 6), pady=(6, 0))
        self._render_sam_body(scroller.inner)

    def _sam_back(self):
        if len(self.plan) and not themed_confirm(
                self.root, "Leave setup", "Discard your selections and go back to the start screen?"):
            return
        self.show_landing()

    def _sam_start_install(self):
        if len(self.plan) == 0:
            show_snackbar(self, "Nothing queued yet — pick at least one action", tone="warn")
            return
        self.show_install_progress(list(self.plan))

    def _sam_update_install_btn(self):
        n = len(self.plan)
        if self._sam_install_btn is not None and self._sam_install_btn.winfo_exists():
            self._sam_install_btn.set_text(f"Install ({n}) [Enter]")
            self._sam_install_btn.set_enabled(n > 0)

    # ---- plan runners ----------------------------------------------------

    def _sam_setup_install_run(self):
        def run(job: Job):
            if not plugin_installed():
                job.log("Installing the SAM plug-in...")
                install_plugin(job)
            else:
                job.log("SAM plug-in already installed.")
            if not backend_ready():
                job.log("Setting up the SAM Python backend...")
                install_sam_backend(job, TORCH_INDEX_URLS[self.torch_choice.get()])
            else:
                job.log("SAM Python backend already ready.")
        return run

    @staticmethod
    def _sam_setup_remove_run(job: Job):
        remove_plugin(job)
        remove_sam_backend(job)

    @staticmethod
    def _sam_model_install_run(spec: ModelSpec):
        def run(job: Job):
            dest = model_path(spec)
            if os.path.isfile(dest):
                job.log(f"{spec.label} already downloaded at {dest}")
                return
            if job.download(spec.url, dest, job.cancel_event):
                write_plugin_settings(spec)
                write_sam_info([spec.key])
        return run

    @staticmethod
    def _sam_model_remove_run(spec: ModelSpec):
        def run(job: Job):
            dest = model_path(spec)
            try:
                if os.path.isdir(dest):
                    shutil.rmtree(dest)
                elif os.path.isfile(dest):
                    os.remove(dest)
                job.log(f"Removed {dest}")
            except Exception as e:
                job.log(f"ERROR removing {dest}: {e}")
        return run

    # ---- the page body ---------------------------------------------------

    def _render_sam_body(self, parent):
        setup_install_key = "sam_setup:install"

        model_widgets: list[tuple] = []       # (card, right_canvas, spec, installed)
        queue_all_buttons: list = []

        # -- PyTorch build selector card --
        card = RoundedCard(parent)
        card.pack(fill="x", pady=(0, 10))
        body = card.body

        row = tk.Frame(body, bg=CARD_BG)
        row.pack(fill="x", padx=4, pady=4)

        tk.Label(row, text="PyTorch build", bg=CARD_BG, fg=TEXT, font=F_BODY_B).pack(
            side="left", padx=(0, 12))

        combo = ctk.CTkComboBox(
            row, variable=self.torch_choice, values=list(TORCH_INDEX_URLS.keys()),
            state="readonly", width=340, height=36, corner_radius=10, font=F_BODY,
            fg_color=FIELD_BG, border_color=CARD_BORDER, border_width=1, text_color=TEXT,
            button_color=FIELD_BG, button_hover_color=SECONDARY_HOVER,
            dropdown_fg_color=FIELD_BG, dropdown_hover_color=SECONDARY_HOVER,
            dropdown_text_color=TEXT, dropdown_font=F_BODY)
        combo.pack(side="left")
        self._pytorch_combo = combo

        combo.bind("<Button-1>", lambda e: combo._clicked(), add="+")
        if hasattr(combo, "_entry"):
            combo._entry.bind("<Button-1>", lambda e: combo._clicked(), add="+")
            try:
                combo._entry.configure(cursor="hand2")
            except Exception:
                pass
        try:
            combo.configure(cursor="hand2")
        except Exception:
            pass

        card.finalize()

        # Queuing any model implies plug-in + backend setup; drop it again
        # when the last model is un-queued.
        def sync_sam_setup_in_plan():
            has_any_model_install = any(self.plan.has(f"sam_model:{spec.key}:install") for spec in MODEL_REGISTRY)
            if self.plan.has("sam3:install"):
                has_any_model_install = True

            if has_any_model_install:
                if not self.plan.has(setup_install_key):
                    self.plan.add(PlannedAction(setup_install_key, "Install SAM plug-in + backend", "install",
                                                self._sam_setup_install_run()))
            else:
                self.plan.discard(setup_install_key)

        # -- models, by family --
        autowrap_label(
            parent,
            "Quality/Speed are rough 1-5 estimates, comparable within a family. Already-downloaded models "
            "are never a checkbox again — Remove just queues their deletion for the final install step.",
            fg=TEXT_MUTED, bg=BG, font=F_SMALL,
        ).pack(anchor="w", fill="x", pady=(6, 10))

        rec_key = recommended_model_key(self.hw)

        def render_family(family_name, family_key, default_expanded):
            fam_card = RoundedCard(parent)
            fam_card.pack(fill="x", pady=(0, 10))
            
            # Collapsible header
            head = tk.Frame(fam_card.body, bg=CARD_BG)
            head.pack(fill="x", pady=(0, 4))
            
            arrow_var = tk.StringVar(value="▼" if default_expanded else "▶")
            arrow_lbl = tk.Label(head, textvariable=arrow_var, bg=CARD_BG, fg=ACCENT, font=F_SECTION)
            arrow_lbl.pack(side="left", padx=(0, 6))
            
            title_lbl = tk.Label(head, text=family_name, bg=CARD_BG, fg=ACCENT, font=F_SECTION)
            title_lbl.pack(side="left")
            
            queue_all_btn = RoundedButton(head, "Queue all missing", icon="install", variant="secondary",
                                           width=170)
            queue_all_btn.pack(side="right")
            queue_all_buttons.append(queue_all_btn)
            
            # Container for models
            container = tk.Frame(fam_card.body, bg=CARD_BG)
            if default_expanded:
                container.pack(fill="x", pady=(4, 0))
                
            # Toggle logic
            def toggle(event=None):
                if container.winfo_viewable():
                    container.pack_forget()
                    arrow_var.set("▶")
                else:
                    container.pack(fill="x", pady=(4, 0))
                    arrow_var.set("▼")
            
            arrow_lbl.bind("<Button-1>", toggle)
            title_lbl.bind("<Button-1>", toggle)
            head.bind("<Button-1>", toggle)
            for w in (arrow_lbl, title_lbl, head):
                try:
                    w.configure(cursor="hand2")
                except Exception:
                    pass

            for spec in [m for m in MODEL_REGISTRY if m.family == family_key]:
                installed = model_installed(spec)
                install_key, remove_key = f"sam_model:{spec.key}:install", f"sam_model:{spec.key}:remove"
                is_queued = self.plan.has(install_key) if not installed else self.plan.has(remove_key)

                if is_queued:
                    card_bg = "#2e1b1d" if installed else "#152e20"
                    card_hover_bg = "#3b2527" if installed else "#1e3d2c"
                    active_border = DANGER if installed else SUCCESS
                    active_width = 2
                else:
                    card_bg = CARD_BG
                    card_hover_bg = "#2f323a"
                    active_border = None
                    active_width = 1

                mrow = RoundedCard(container, bg=card_bg, border=CARD_BORDER,
                                   hover_bg=card_hover_bg, active_border=active_border,
                                   active_width=active_width, hover_border=ACCENT, pad=14, radius=16)
                mrow.pack(fill="x", pady=6)
                rbody = mrow.body
                top = tk.Frame(rbody, bg=card_bg)
                top.pack(fill="both", expand=True)

                left = tk.Frame(top, bg=card_bg)
                left.pack(side="left", fill="x", expand=True)
                name_row = tk.Frame(left, bg=card_bg)
                name_row.pack(anchor="w")
                tk.Label(name_row, text=spec.label, bg=card_bg, fg=TEXT, font=F_ITEM_TITLE).pack(
                    side="left")
                tk.Label(name_row, text=f"   {spec.size}", bg=card_bg, fg=TEXT_MUTED, font=F_SMALL).pack(
                    side="left")
                if spec.key == rec_key:
                    tk.Label(name_row, text="  ★ Recommended", bg=card_bg, fg=ACCENT,
                             font=F_SMALL_B).pack(side="left")
                rating_widget(left, spec.quality, spec.speed, bg=card_bg).pack(anchor="w", pady=(4, 0))

                right = tk.Frame(top, bg=card_bg)
                right.pack(side="right", padx=(16, 0), fill="y")

                model_shortcuts = {
                    "sam_vit_b": "1",
                    "sam_vit_l": "2",
                    "sam_vit_h": "3",
                    "sam2_hiera_tiny": "4",
                }
                shortcut_num = model_shortcuts.get(spec.key)
                if shortcut_num:
                    tk.Label(right, text=f"({shortcut_num})", bg=card_bg, fg=TEXT_MUTED, font=F_SMALL_B).pack(
                        side="left", padx=(0, 10))

                if installed:
                    rik, ric = ("trash", DANGER) if is_queued else ("check", SUCCESS)
                else:
                    rik, ric = ("check", SUCCESS) if is_queued else ("circle", CARD_BORDER)

                right_canvas = icon_canvas(right, rik, color=ric, size=28, bg=card_bg)
                right_canvas.pack(side="left", anchor="center", expand=True)

                def make_toggle_cmd(s=spec, inst=installed):
                    ikey, rkey = f"sam_model:{s.key}:install", f"sam_model:{s.key}:remove"
                    def cmd():
                        if inst:
                            self.plan.toggle(PlannedAction(rkey, f"Remove {s.label}", "remove",
                                                            self._sam_model_remove_run(s)))
                        else:
                            self.plan.toggle(PlannedAction(ikey, f"Download {s.label}", "install",
                                                            self._sam_model_install_run(s)))
                        sync_sam_setup_in_plan()
                        refresh_sam_page()
                    return cmd

                mrow._command = make_toggle_cmd()
                self._sam_cards[f"sam_model:{spec.key}"] = mrow._command
                model_widgets.append((mrow, right_canvas, spec, installed))
                mrow.finalize()
            fam_card.finalize()
            return queue_all_btn

        def queue_all(family):
            missing = [m for m in MODEL_REGISTRY if m.family == family and not model_installed(m)]
            if not missing:
                themed_info(self.root, "Nothing to do", f"All {family} models are already installed.")
                return
            for spec in missing:
                key = f"sam_model:{spec.key}:install"
                if not self.plan.has(key):
                    self.plan.add(PlannedAction(key, f"Download {spec.label}", "install",
                                                 self._sam_model_install_run(spec)))
            sync_sam_setup_in_plan()
            refresh_sam_page()

        # Render SAM 2 first (expanded by default)
        qbtn_sam2 = render_family("SAM 2", "SAM2", True)

        # Render SAM 3.1 second (expanded by default)
        sam3_widgets = self._render_sam3_card(
            parent, on_toggle=lambda: (sync_sam_setup_in_plan(), refresh_sam_page()))

        # Render SAM 1 last (collapsed by default)
        qbtn_sam1 = render_family("SAM 1", "SAM1", False)

        qbtn_sam2.command = lambda: queue_all("SAM2")
        self._sam_cards["queue_all_sam2"] = qbtn_sam2.command

        qbtn_sam1.command = lambda: queue_all("SAM1")
        self._sam_cards["queue_all_sam1"] = qbtn_sam1.command

        def refresh_sam_page():
            for mcard, rcanvas, spec, installed in model_widgets:
                ikey, rkey = f"sam_model:{spec.key}:install", f"sam_model:{spec.key}:remove"
                q = self.plan.has(rkey) if installed else self.plan.has(ikey)

                if q:
                    mcard._bg = "#2e1b1d" if installed else "#152e20"
                    mcard._hover_bg = "#3b2527" if installed else "#1e3d2c"
                    mcard._active_border = DANGER if installed else SUCCESS
                    mcard._active_width = 2

                    rik, ric = ("trash", DANGER) if installed else ("check", SUCCESS)
                else:
                    mcard._bg = CARD_BG
                    mcard._hover_bg = "#2f323a"
                    mcard._active_border = None
                    mcard._active_width = 1

                    rik, ric = ("check", SUCCESS) if installed else ("circle", CARD_BORDER)

                rcanvas.delete("all")
                blit_icon(rcanvas, 14, 14, rik, color=ric, size=28)
                mcard._update_colors()

            for qbtn in queue_all_buttons:
                qbtn.set_enabled(True)
            sam3_widgets.refresh(True)
            self._sam_update_install_btn()

        self._refresh_sam_page_fn = refresh_sam_page
        refresh_sam_page()

    # -- SAM 3.1 (gated on Hugging Face) ----------------------------------

    class _Sam3Widgets:
        def __init__(self, refresh_fn):
            self._refresh_fn = refresh_fn

        def refresh(self, present: bool):
            self._refresh_fn(present)

    def _render_sam3_card(self, parent, on_toggle=None):
        spec = MODEL_BY_KEY["sam3"]
        installed = model_installed(spec)
        card = RoundedCard(parent)
        card.pack(fill="x", pady=(0, 10))
        body = card.body

        # Collapsible header
        head = tk.Frame(body, bg=CARD_BG)
        head.pack(fill="x", pady=(0, 4))
        
        arrow_var = tk.StringVar(value="▼")
        arrow_lbl = tk.Label(head, textvariable=arrow_var, bg=CARD_BG, fg=ACCENT, font=F_SECTION)
        arrow_lbl.pack(side="left", padx=(0, 6))
        
        title_lbl = tk.Label(head, text="SAM 3 (5)", bg=CARD_BG, fg=ACCENT, font=F_SECTION)
        title_lbl.pack(side="left")
        
        container = tk.Frame(body, bg=CARD_BG)
        container.pack(fill="x", pady=(4, 0))
        
        def toggle_collapse(event=None):
            if container.winfo_viewable():
                container.pack_forget()
                arrow_var.set("▶")
            else:
                container.pack(fill="x", pady=(4, 0))
                arrow_var.set("▼")
                
        arrow_lbl.bind("<Button-1>", toggle_collapse)
        title_lbl.bind("<Button-1>", toggle_collapse)
        head.bind("<Button-1>", toggle_collapse)
        for w in (arrow_lbl, title_lbl, head):
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass

        # Top row inside container
        top = tk.Frame(container, bg=CARD_BG)
        top.pack(fill="x")
        left = tk.Frame(top, bg=CARD_BG)
        left.pack(side="left", fill="x", expand=True)
        name_row = tk.Frame(left, bg=CARD_BG)
        name_row.pack(anchor="w")
        tk.Label(name_row, text=f"{spec.label} details", bg=CARD_BG, fg=TEXT, font=F_ITEM_TITLE).pack(
            side="left")
        tk.Label(name_row, text=f"   {spec.size}", bg=CARD_BG, fg=TEXT_MUTED, font=F_SMALL).pack(side="left")
        rating_widget(left, spec.quality, spec.speed, bg=CARD_BG).pack(anchor="w", pady=(4, 0))

        install_key, remove_key = "sam3:install", "sam3:remove"

        autowrap_label(
            container, f"Gated on Hugging Face ({SAM3_HF_REPO_ID}) — request access, wait for approval, then "
                  "paste a READ token below. The token is only checked against the repo once the plan "
                  "actually runs, so queuing it now is free.",
            fg=TEXT_MUTED, bg=CARD_BG, font=F_SMALL,
        ).pack(anchor="w", fill="x", pady=(12, 14))

        row1 = tk.Frame(container, bg=CARD_BG)
        row1.pack(fill="x", pady=(0, 10))
        RoundedButton(row1, "Request access on Hugging Face", icon="link", variant="secondary", width=270,
                      command=lambda: webbrowser.open(SAM3_HF_PAGE)).pack(side="left")
        transformers_key = "sam3:transformers"
        transformers_btn = RoundedButton(row1, "Install/upgrade transformers", icon="box", variant="success",
                                          width=230)
        transformers_btn.pack(side="left", padx=8)

        def toggle_transformers():
            self.plan.toggle(PlannedAction(transformers_key, "Install/upgrade transformers", "install",
                                            lambda job: install_sam3_transformers(job)))
            transformers_btn.set_text("Install/upgrade transformers"
                                       + (" ✓" if self.plan.has(transformers_key) else ""))
            self._sam_update_install_btn()

        transformers_btn.command = toggle_transformers

        row2 = tk.Frame(container, bg=CARD_BG)
        row2.pack(fill="x")
        tk.Label(row2, text="HF token", bg=CARD_BG, fg=TEXT, font=F_BODY_B).pack(side="left")
        hf_entry = ctk.CTkEntry(row2, textvariable=self.hf_token_var, show="•", width=300, height=36,
                                corner_radius=10, font=F_BODY, fg_color=FIELD_BG,
                                border_color=CARD_BORDER, border_width=1, text_color=TEXT)
        hf_entry.pack(side="left", padx=8)
        self._hf_token_entry = hf_entry

        if installed:
            sam3_btn = RoundedButton(row2, "Remove", icon="trash", variant="danger", width=130)
            sam3_btn.pack(side="left")

            def toggle_sam3():
                self.plan.toggle(PlannedAction(remove_key, "Remove SAM 3.1", "remove",
                                                lambda job: remove_sam3(job)))
                sam3_btn.set_text("Remove" + (" ✓" if self.plan.has(remove_key) else ""))
                if on_toggle:
                    on_toggle()

            self._sam_cards["sam3"] = toggle_sam3
            sam3_btn.command = toggle_sam3

            def refresh(_present: bool):
                pass
        else:
            sam3_btn = RoundedButton(
                row2, "Add to plan", icon="install", variant="success", width=140,
                on_blocked=lambda: show_snackbar(self, "Enter a Hugging Face token first", tone="warn"))
            sam3_btn.pack(side="left")

            def token_entered() -> bool:
                return bool(self.hf_token_var.get().strip())

            def toggle_sam3():
                self.plan.toggle(PlannedAction(install_key, "Download SAM 3.1", "install",
                                                lambda job: self._run_sam3_download(job)))
                sam3_btn.set_text("Add to plan" + (" ✓" if self.plan.has(install_key) else ""))
                if on_toggle:
                    on_toggle()

            self._sam_cards["sam3"] = toggle_sam3
            sam3_btn.command = toggle_sam3

            def refresh(present: bool):
                queued = self.plan.has(install_key)
                sam3_btn.set_enabled(queued or token_entered())

            trace_id = self.hf_token_var.trace_add("write", lambda *_a: refresh(True))

            def _drop_token_trace(_e=None, tid=trace_id):
                try:
                    self.hf_token_var.trace_remove("write", tid)
                except (tk.TclError, ValueError):
                    pass

            sam3_btn.bind("<Destroy>", _drop_token_trace)

        refresh(True)
        card.finalize()
        return self._Sam3Widgets(refresh)

    def _run_sam3_download(self, job: Job):
        token = self.hf_token_var.get().strip()
        if not token:
            job.log("No Hugging Face token was entered — skipping SAM 3.1.")
            return
        ok, tag = download_sam3(job, token)
        if not ok:
            job.log(sam3_failure_message(tag))
