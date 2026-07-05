#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import gi

gi.require_version("Gimp", "3.0")
from gi.repository import Gimp

gi.require_version("GimpUi", "3.0")
from gi.repository import GimpUi

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk

gi.require_version("Gegl", "0.4")
from gi.repository import GObject, Gio, Gegl
from gi.repository import GLib


import tempfile
import subprocess
import threading
from os.path import exists
from array import array
import random
import os
import sys
import glob
import struct
import json
import logging
import math

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

# ---------------------------------------------------------------------------
# LazyGimp backend auto-discovery.
#
# LazyGimp (a companion installer) sets up a dedicated venv + downloads a SAM
# checkpoint under ~/.local/share/lazygimp/segany/. When that's present, the
# plug-in should never leave the user staring at two empty file choosers —
# it already knows exactly where the interpreter and the models are. This is
# what makes the dialog "just work" on first run without ever making the
# user hunt for paths.
# ---------------------------------------------------------------------------

LAZYGIMP_BACKEND_DIR = os.path.expanduser("~/.local/share/lazygimp/segany")

MODEL_FRIENDLY_LABELS = {
    "sam_vit_b_01ec64": "SAM1 · vit_b — lightest, fastest on CPU",
    "sam_vit_l_0b3195": "SAM1 · vit_l — balanced (recommended)",
    "sam_vit_h_4b8939": "SAM1 · vit_h — best quality, slow on CPU",
    "sam2_hiera_tiny": "SAM2 · tiny",
    "sam2_hiera_small": "SAM2 · small",
    "sam2_hiera_base_plus": "SAM2 · base+",
    "sam2_hiera_large": "SAM2 · large",
    "sam3": "SAM3 · concept segmentation (text prompts, HF access required — runs on CPU too, GPU just makes it faster)",
}

# SAM3 is a text-prompted "concept segmentation" model rather than a
# point/box automatic-mask generator like SAM1/2, and its checkpoint is a
# gated Hugging Face snapshot directory (several files), not a single .pth.
# We recognise it by this sentinel folder name inside the backend's models/
# directory rather than by a file extension.
SAM3_MODEL_DIRNAME = "sam3"


def discover_lazygimp_backend():
    """Return (python_path_or_None, [checkpoint paths...]) from the LazyGimp
    managed backend directory, if it exists. Never raises.

    Entries are either a single checkpoint FILE (SAM1/SAM2, .pth/.pt/
    .safetensors) or a DIRECTORY (SAM3's gated Hugging Face snapshot, which
    is several files, not one)."""
    python_path = None
    models = []
    try:
        venv_python = os.path.join(LAZYGIMP_BACKEND_DIR, "venv", "bin", "python3")
        if os.path.isfile(venv_python) and os.access(venv_python, os.X_OK):
            python_path = venv_python
        models_dir = os.path.join(LAZYGIMP_BACKEND_DIR, "models")
        if os.path.isdir(models_dir):
            for fname in sorted(os.listdir(models_dir)):
                fpath = os.path.join(models_dir, fname)
                if fname.lower().endswith((".pth", ".pt", ".safetensors")):
                    models.append(fpath)
                elif fname == SAM3_MODEL_DIRNAME and os.path.isdir(fpath) and os.listdir(fpath):
                    models.append(fpath)
    except OSError as e:
        logging.info("LazyGimp backend discovery failed: %s", e)
    return python_path, models


def is_sam3_path(path):
    return path is not None and os.path.basename(path.rstrip("/")) == SAM3_MODEL_DIRNAME


def model_friendly_label(path):
    if is_sam3_path(path):
        return MODEL_FRIENDLY_LABELS["sam3"]
    stem = os.path.splitext(os.path.basename(path))[0]
    label = MODEL_FRIENDLY_LABELS.get(stem)
    return f"{label}  ({os.path.basename(path)})" if label else os.path.basename(path)


class DialogValue:
    def __init__(self, filepath):
        data = None
        self.pythonPath = None
        self.modelType = "Auto"
        self.checkPtPath = None
        self.maskType = "Multiple"
        self.segType = "Auto"
        self.isRandomColor = True
        self.maskColor = [255, 0, 0, 255]
        self.selPtCnt = 10
        self.selBoxPathName = None
        self.segRes = "Medium"
        self.cropNLayers = 0
        self.minMaskArea = 0
        # 0 = no downscale. Auto-mode's cost is dominated by points-per-side,
        # not resolution, but very large photos still pay a real cost in
        # mask post-processing/upscaling, so this remains a useful knob for
        # power users — see seganybridge.py for the actual math.
        self.maxAutoDim = 1024
        # SAM3 is a text-prompted "concept" segmenter, not a point/box model
        # like SAM1/2 — this is the noun phrase it looks for (e.g. "car").
        self.textPrompt = ""

        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                self.pythonPath = data.get("pythonPath", self.pythonPath)
                self.modelType = data.get("modelType", self.modelType)
                self.checkPtPath = data.get("checkPtPath", self.checkPtPath)
                self.maskType = data.get("maskType", self.maskType)
                self.segType = data.get("segType", self.segType)
                self.isRandomColor = data.get("isRandomColor", self.isRandomColor)
                self.maskColor = data.get("maskColor", self.maskColor)
                self.selPtCnt = data.get("selPtCnt", self.selPtCnt)
                self.segRes = data.get("segRes", self.segRes)
                self.cropNLayers = data.get("cropNLayers", self.cropNLayers)
                self.minMaskArea = data.get("minMaskArea", self.minMaskArea)
                self.maxAutoDim = data.get("maxAutoDim", self.maxAutoDim)
                self.textPrompt = data.get("textPrompt", self.textPrompt)
        except Exception as e:
            logging.info("Error reading json : %s" % e)

    def persist(self, filepath):
        data = {
            "pythonPath": self.pythonPath,
            "modelType": self.modelType,
            "checkPtPath": self.checkPtPath,
            "maskType": self.maskType,
            "segType": self.segType,
            "isRandomColor": self.isRandomColor,
            "maskColor": self.maskColor,
            "selPtCnt": self.selPtCnt,
            "segRes": self.segRes,
            "cropNLayers": self.cropNLayers,
            "minMaskArea": self.minMaskArea,
            "maxAutoDim": self.maxAutoDim,
            "textPrompt": self.textPrompt,
        }
        with open(filepath, "w") as f:
            json.dump(data, f)


class OptionsDialog(Gtk.Dialog):
    def __init__(self, image, boxPathDict):
        Gtk.Dialog.__init__(self, title="Segment Anything", transient_for=None, flags=0)
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK
        )

        self.set_default_size(440, 240)

        self.boxPathNames = sorted(boxPathDict.keys())
        boxPathExist = len(self.boxPathNames) > 0
        self.isGrayScale = image.get_base_type() == Gimp.ImageType.GRAYA_IMAGE
        scriptDir = os.path.dirname(os.path.abspath(__file__))
        self.configFilePath = os.path.join(scriptDir, "segany_settings.json")

        self.values = DialogValue(self.configFilePath)
        self._discovered_python, self._discovered_models = discover_lazygimp_backend()

        outer = self.get_content_area()
        outer.set_spacing(8)
        outer.set_border_width(4)

        # ------------------------------------------------------------------
        # Simple section — everything a first-time user needs, nothing else.
        # ------------------------------------------------------------------
        grid = Gtk.Grid()
        grid.set_column_spacing(10)
        grid.set_row_spacing(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(6)
        outer.add(grid)

        row = 0

        # Model — auto-discovered from the LazyGimp backend, or a single
        # "current configuration" entry if the plug-in was set up by hand.
        self.modelLbl = Gtk.Label(label="Model:", xalign=1)
        self.modelCombo = Gtk.ComboBoxText()
        # GTK sizes a ComboBoxText to fit only its currently-selected entry,
        # not the widest one it holds — with labels like "SAM2 · hiera_tiny
        # (sam2_hiera_tiny.pt)" that made both the closed combo and its
        # popdown list render too narrow to read at a glance. A fixed
        # minimum width fixes both at once, since GTK derives the popdown's
        # width from the combo's own allocation.
        self.modelCombo.set_size_request(320, -1)
        self._model_paths = []  # combo index -> checkpoint path

        self.noModelHintLbl = Gtk.Label(xalign=0)
        self.noModelHintLbl.set_line_wrap(True)
        self.noModelHintLbl.set_markup(
            "<small>No model found automatically. Install one with the "
            "gimpsegany installer (or LazyGimp), or set the paths manually "
            "below in <b>Expert Mode</b>.</small>"
        )

        self._populate_model_combo()
        grid.attach(self.modelLbl, 0, row, 1, 1)
        grid.attach(self.modelCombo, 1, row, 1, 1)
        row += 1

        grid.attach(self.noModelHintLbl, 0, row, 2, 1)
        row += 1

        # Text Prompt — only meaningful for SAM3 (a concept segmenter: it
        # looks for every instance of a noun phrase, e.g. "car" or "person
        # wearing a red hat"), hidden entirely for SAM1/SAM2 models.
        self.textPromptLbl = Gtk.Label(label="Text Prompt:", xalign=1)
        self.textPromptEntry = Gtk.Entry()
        self.textPromptEntry.set_text(self.values.textPrompt)
        self.textPromptEntry.set_placeholder_text("e.g. \"car\", \"red flower\"")
        grid.attach(self.textPromptLbl, 0, row, 1, 1)
        grid.attach(self.textPromptEntry, 1, row, 1, 1)
        row += 1

        # Segmentation Type
        self.segTypeLbl = Gtk.Label(label="Segmentation Type:", xalign=1)
        self.segTypeDropDown = Gtk.ComboBoxText()
        self.segTypeVals = ["Auto", "Box", "Selection"]
        for value in self.segTypeVals:
            self.segTypeDropDown.append_text(value)
        self.segTypeDropDown.set_active(self.segTypeVals.index(self.values.segType))
        grid.attach(self.segTypeLbl, 0, row, 1, 1)
        grid.attach(self.segTypeDropDown, 1, row, 1, 1)
        row += 1

        # Selection Points
        self.selPtsLbl = Gtk.Label(label="Selection Points:", xalign=1)
        self.selPtsEntry = Gtk.Entry()
        self.selPtsEntry.set_text(str(self.values.selPtCnt))
        grid.attach(self.selPtsLbl, 0, row, 1, 1)
        grid.attach(self.selPtsEntry, 1, row, 1, 1)
        row += 1

        # Mask Type
        self.maskTypeLbl = Gtk.Label(label="Mask Type:", xalign=1)
        self.maskTypeDropDown = Gtk.ComboBoxText()
        self.maskTypeVals = ["Multiple", "Single"]
        for value in self.maskTypeVals:
            self.maskTypeDropDown.append_text(value)
        self.maskTypeDropDown.set_active(self.maskTypeVals.index(self.values.maskType))
        grid.attach(self.maskTypeLbl, 0, row, 1, 1)
        grid.attach(self.maskTypeDropDown, 1, row, 1, 1)
        row += 1

        if not self.isGrayScale:
            self.randColBtn = Gtk.CheckButton(label="Random Mask Color")
            self.randColBtn.set_active(self.values.isRandomColor)
            grid.attach(self.randColBtn, 1, row, 1, 1)
            row += 1

            self.maskColorLbl = Gtk.Label(label="Mask Color:", xalign=1)
            self.maskColorBtn = Gtk.ColorButton()
            rgba = Gdk.RGBA()
            rgba.parse(
                f"rgb({self.values.maskColor[0]},{self.values.maskColor[1]},{self.values.maskColor[2]})"
            )
            self.maskColorBtn.set_rgba(rgba)
            grid.attach(self.maskColorLbl, 0, row, 1, 1)
            grid.attach(self.maskColorBtn, 1, row, 1, 1)
            row += 1

        # ------------------------------------------------------------------
        # Expert mode — collapsed by default. Raw paths, model-family
        # override, and the numeric SAM2/SAM1 auto-segmentation tuning that
        # only matters to someone who already knows what it does.
        # ------------------------------------------------------------------
        self.expertExpander = Gtk.Expander(label="Expert Mode")
        outer.add(self.expertExpander)

        egrid = Gtk.Grid()
        egrid.set_column_spacing(10)
        egrid.set_row_spacing(8)
        egrid.set_margin_start(10)
        egrid.set_margin_end(10)
        egrid.set_margin_top(8)
        egrid.set_margin_bottom(8)
        self.expertExpander.add(egrid)

        erow = 0

        pythonFileLbl = Gtk.Label(label="Python3 Path:", xalign=1)
        self.pythonFileBtn = Gtk.FileChooserButton(title="Select Python Path")
        pre_python = self.values.pythonPath or self._discovered_python
        if pre_python is not None:
            self.pythonFileBtn.set_filename(pre_python)
        egrid.attach(pythonFileLbl, 0, erow, 1, 1)
        egrid.attach(self.pythonFileBtn, 1, erow, 1, 1)
        erow += 1

        # NOTE: there used to be a second "Model Type" combo here, meant as a
        # manual override of the family/variant (SAM1 vit_h/vit_l/vit_b, SAM2
        # hiera size, SAM3) picked up from the checkpoint below. It was
        # removed: seganybridge.py always decides the model FAMILY from the
        # checkpoint filename/folder itself ("sam_" prefix / "sam2" prefix /
        # a folder literally named "sam3") no matter what this combo said, so
        # it could never actually fix a family misdetection. Its only real
        # effect was letting a checkpoint with a recognised prefix but a
        # non-standard exact filename skip the strict name lookup — an edge
        # case better handled by the inline hint below (which tells you
        # exactly what to rename the file to) than by a whole second control
        # that silently did nothing for the more common failure mode.
        self.checkPtFileLbl = Gtk.Label(
            label="Model Checkpoint (.pth/.safetensors):", xalign=1
        )
        self.checkPtFileBtn = Gtk.FileChooserButton(
            title="Select Model Checkpoint Path"
        )
        if self.values.checkPtPath is not None:
            if is_sam3_path(self.values.checkPtPath):
                self.checkPtFileBtn.set_action(Gtk.FileChooserAction.SELECT_FOLDER)
            self.checkPtFileBtn.set_filename(self.values.checkPtPath)
        egrid.attach(self.checkPtFileLbl, 0, erow, 1, 1)
        egrid.attach(self.checkPtFileBtn, 1, erow, 1, 1)
        erow += 1

        self.checkPtHintLbl = Gtk.Label(xalign=0)
        self.checkPtHintLbl.set_line_wrap(True)
        self.checkPtHintLbl.set_markup(
            "<small>Unrecognised file name — the model family/variant is "
            f"auto-detected from it. Expected one of: {', '.join(sorted(MODEL_FRIENDLY_LABELS.keys() - {'sam3'}))} "
            "(with .pth/.pt/.safetensors), or a folder named \"sam3\".</small>"
        )
        egrid.attach(self.checkPtHintLbl, 0, erow, 2, 1)
        erow += 1

        self.segResLbl = Gtk.Label(label="Segmentation Resolution:", xalign=1)
        self.segResDropDown = Gtk.ComboBoxText()
        self.segResVals = ["Low", "Medium", "High"]
        for value in self.segResVals:
            self.segResDropDown.append_text(value)
        self.segResDropDown.set_active(self.segResVals.index(self.values.segRes))
        egrid.attach(self.segResLbl, 0, erow, 1, 1)
        egrid.attach(self.segResDropDown, 1, erow, 1, 1)
        erow += 1

        self.cropNLayersLbl = Gtk.Label(label="Crop n Layers:", xalign=1)
        self.cropNLayersChk = Gtk.CheckButton()
        self.cropNLayersChk.set_active(self.values.cropNLayers > 0)
        egrid.attach(self.cropNLayersLbl, 0, erow, 1, 1)
        egrid.attach(self.cropNLayersChk, 1, erow, 1, 1)
        erow += 1

        self.minMaskAreaLbl = Gtk.Label(label="Minimum Mask Area (px²):", xalign=1)
        self.minMaskAreaEntry = Gtk.Entry()
        self.minMaskAreaEntry.set_text(str(self.values.minMaskArea))
        self.minMaskAreaEntry.set_tooltip_text(
            "Masks smaller than this many pixels are discarded — it's an AREA (width × height), not a "
            "diameter or side length. 0 keeps everything. The hint below converts it to an equivalent "
            "brush size so you can judge it visually: pick a circular brush of that diameter and anything "
            "it can't cover in one dab gets thrown away."
        )
        egrid.attach(self.minMaskAreaLbl, 0, erow, 1, 1)
        egrid.attach(self.minMaskAreaEntry, 1, erow, 1, 1)
        erow += 1

        self.minMaskAreaHintLbl = Gtk.Label(xalign=0)
        self.minMaskAreaHintLbl.set_line_wrap(True)
        egrid.attach(self.minMaskAreaHintLbl, 0, erow, 2, 1)
        erow += 1

        self.maxAutoDimLbl = Gtk.Label(label="Max resolution for Auto (0 = no limit):", xalign=1)
        self.maxAutoDimSpin = Gtk.SpinButton()
        self.maxAutoDimSpin.set_range(0, 8192)
        self.maxAutoDimSpin.set_increments(128, 512)
        self.maxAutoDimSpin.set_value(self.values.maxAutoDim)
        egrid.attach(self.maxAutoDimLbl, 0, erow, 1, 1)
        egrid.attach(self.maxAutoDimSpin, 1, erow, 1, 1)
        erow += 1

        # Open Expert mode by default only if we have nothing to offer in
        # Simple mode — otherwise stay out of the way.
        self.expertExpander.set_expanded(len(self._discovered_models) == 0 and not self.values.checkPtPath)

        self.connect("map-event", self.on_map_event)
        self.segTypeDropDown.connect("changed", self.update_options_visibility)
        self.modelCombo.connect("changed", self.on_model_combo_changed)
        self.checkPtFileBtn.connect("file-set", self.update_options_visibility)
        self.minMaskAreaEntry.connect("changed", self.on_min_mask_area_changed)
        self.on_min_mask_area_changed(self.minMaskAreaEntry)
        if not self.isGrayScale:
            self.randColBtn.connect("toggled", self.on_random_toggled)

        # The combo's initial selection was set inside _populate_model_combo()
        # *before* the "changed" signal above existed, so it never actually
        # copied its selection into the Expert-mode checkpoint/python fields.
        # Do that sync once now that every widget involved exists.
        if self._model_paths:
            self.on_model_combo_changed(self.modelCombo)
        else:
            self.update_options_visibility(None)

        self.show_all()

    def _populate_model_combo(self):
        self._model_paths = []
        current = self.values.checkPtPath
        current_is_discovered = current in self._discovered_models

        if current and not current_is_discovered:
            self.modelCombo.append_text(f"Current: {os.path.basename(current.rstrip('/'))}")
            self._model_paths.append(current)

        for path in self._discovered_models:
            self.modelCombo.append_text(model_friendly_label(path))
            self._model_paths.append(path)

        has_models = len(self._model_paths) > 0
        self.modelCombo.set_visible(has_models)
        self.modelLbl.set_visible(has_models)
        self.noModelHintLbl.set_visible(not has_models)

        if has_models:
            if current in self._model_paths:
                self.modelCombo.set_active(self._model_paths.index(current))
            else:
                self.modelCombo.set_active(0)

    def on_model_combo_changed(self, widget):
        idx = self.modelCombo.get_active()
        if idx < 0 or idx >= len(self._model_paths):
            return
        path = self._model_paths[idx]
        if is_sam3_path(path):
            self.checkPtFileBtn.set_action(Gtk.FileChooserAction.SELECT_FOLDER)
        else:
            self.checkPtFileBtn.set_action(Gtk.FileChooserAction.OPEN)
        self.checkPtFileBtn.set_filename(path)
        if not self.pythonFileBtn.get_filename() and self._discovered_python:
            self.pythonFileBtn.set_filename(self._discovered_python)
        self.update_options_visibility(None)

    def update_options_visibility(self, widget):
        segType = self.segTypeVals[self.segTypeDropDown.get_active()]

        isAuto = segType == "Auto"

        checkpoint_path = self.checkPtFileBtn.get_filename()
        isSam3 = is_sam3_path(checkpoint_path)

        # The model family/variant is always inferred from the checkpoint's
        # own file name (see seganybridge.py) — flag it right here instead
        # of letting the user find out only after the subprocess fails.
        stem = (
            os.path.splitext(os.path.basename(checkpoint_path))[0]
            if checkpoint_path and not isSam3
            else None
        )
        unrecognised = bool(stem) and stem not in (MODEL_FRIENDLY_LABELS.keys() - {"sam3"})
        self.checkPtHintLbl.set_visible(unrecognised)

        # SAM3 is a text-prompted concept segmenter, not a point/box/auto
        # model like SAM1/SAM2 — swap the whole "how do I select" section
        # for a single text prompt field instead of hiding/showing pieces
        # of the SAM1/2 workflow that don't apply to it.
        self.segTypeLbl.set_visible(not isSam3)
        self.segTypeDropDown.set_visible(not isSam3)
        self.textPromptLbl.set_visible(isSam3)
        self.textPromptEntry.set_visible(isSam3)
        self.checkPtFileLbl.set_text(
            "Model Folder (SAM3 snapshot):"
            if isSam3
            else "Model Checkpoint (.pth/.safetensors):"
        )

        self.selPtsLbl.set_visible(not isSam3 and segType in ["Selection"])
        self.selPtsEntry.set_visible(not isSam3 and segType in ["Selection"])
        self.maskTypeLbl.set_visible(isSam3 or segType not in ["Auto"])
        self.maskTypeDropDown.set_visible(isSam3 or segType not in ["Auto"])

        # Both SAM1 and SAM2 honour these now; only hide them outside Auto,
        # and always hide them for SAM3 (they're not part of its API).
        show_auto_options = isAuto and not isSam3
        self.segResLbl.set_visible(show_auto_options)
        self.segResDropDown.set_visible(show_auto_options)
        self.cropNLayersLbl.set_visible(show_auto_options)
        self.cropNLayersChk.set_visible(show_auto_options)
        self.minMaskAreaLbl.set_visible(show_auto_options)
        self.minMaskAreaEntry.set_visible(show_auto_options)
        self.minMaskAreaHintLbl.set_visible(show_auto_options)
        self.maxAutoDimLbl.set_visible(show_auto_options)
        self.maxAutoDimSpin.set_visible(show_auto_options)

    def on_min_mask_area_changed(self, widget):
        text = self.minMaskAreaEntry.get_text().strip()
        try:
            area = int(text)
        except ValueError:
            area = None
        if area is None or area <= 0:
            self.minMaskAreaHintLbl.set_markup(
                "<small>0 (or blank) keeps every mask, however small.</small>"
            )
            return
        # Not a real-world constraint on the mask's shape — just a scale
        # reference: "what's the smallest circular brush dab that would
        # survive this filter", since px² alone gives most people no
        # intuition at all for how big a blob that actually is on screen.
        diameter = 2.0 * math.sqrt(area / math.pi)
        self.minMaskAreaHintLbl.set_markup(
            f"<small>≈ the area of a filled circle {diameter:.0f}px across — try setting a brush to "
            f"that size to see how big that is on your image. Anything smaller than {area}px² is discarded.</small>"
        )

    def on_random_toggled(self, widget):
        is_random = self.randColBtn.get_active()
        self.maskColorLbl.set_visible(not is_random)
        self.maskColorBtn.set_visible(not is_random)

    def on_map_event(self, widget, event):
        self.update_options_visibility(None)
        if not self.isGrayScale:
            self.on_random_toggled(self.randColBtn)

    def get_values(self):
        self.values.pythonPath = self.pythonFileBtn.get_filename()
        # Always "Auto": the model family/variant is inferred from the
        # checkpoint's file name by seganybridge.py — see the note above the
        # (now removed) Model Type combo in __init__.
        self.values.modelType = "Auto"
        self.values.checkPtPath = self.checkPtFileBtn.get_filename()
        isSam3 = is_sam3_path(self.values.checkPtPath)
        self.values.segType = "Text" if isSam3 else self.segTypeVals[self.segTypeDropDown.get_active()]
        self.values.textPrompt = self.textPromptEntry.get_text()
        self.values.maskType = self.maskTypeVals[self.maskTypeDropDown.get_active()]
        if hasattr(self, "randColBtn"):
            self.values.isRandomColor = self.randColBtn.get_active()
            rgba = self.maskColorBtn.get_rgba()
            self.values.maskColor = [
                int(rgba.red * 255),
                int(rgba.green * 255),
                int(rgba.blue * 255),
                255,
            ]
        self.values.selPtCnt = int(self.selPtsEntry.get_text())
        self.values.segRes = self.segResVals[self.segResDropDown.get_active()]
        self.values.cropNLayers = 1 if self.cropNLayersChk.get_active() else 0
        self.values.minMaskArea = int(self.minMaskAreaEntry.get_text())
        self.values.maxAutoDim = int(self.maxAutoDimSpin.get_value())
        self.values.persist(self.configFilePath)

        run_values = self.values
        if run_values.modelType == "Auto":
            run_values.modelType = "auto"
        else:
            run_values.modelType = run_values.modelType.split(" ")[0]

        return run_values


def getPathDict(image):
    return {}


def unpackBoolArray(filepath):
    with open(filepath, "rb") as file:
        packed_data = bytearray(file.read())

    byte_index = 8  # Skip the first 8 bytes for num_rows and num_cols

    num_rows = struct.unpack(">I", packed_data[:4])[0]
    num_cols = struct.unpack(">I", packed_data[4:8])[0]

    unpacked_data = []
    bit_position = 0

    for _ in range(num_rows):
        unpacked_row = []
        for _ in range(num_cols):
            if bit_position == 0:
                current_byte = packed_data[byte_index]
                byte_index += 1

            boolean_value = (current_byte >> bit_position) & 1
            unpacked_row.append(boolean_value)
            bit_position += 1

            if bit_position == 8:
                bit_position = 0

        unpacked_data.append(unpacked_row)

    return unpacked_data


def readMaskFile(filepath, formatBinary):
    if formatBinary:
        return unpackBoolArray(filepath)
    else:
        mask = []
        with open(filepath, "r") as f:
            lines = f.readlines()
        for line in lines:
            mask.append([val == "1" for val in line])
        return mask


def exportSelection(image, expfile, exportCnt):
    procedure = Gimp.get_pdb().lookup_procedure("gimp-selection-bounds")
    config = procedure.create_config()
    config.set_property("image", image)
    result = procedure.run(config)
    non_empty = result.index(1)
    x1 = result.index(2)
    y1 = result.index(3)
    x2 = result.index(4)
    y2 = result.index(5)

    if not non_empty:
        return

    coords = []
    numPts = (x2 - x1) * (y2 - y1)
    if exportCnt >= numPts:
        selIdxs = range(numPts)
    else:
        selIdxs = random.sample(range(numPts), exportCnt)
    for selIdx in selIdxs:
        x = x1 + selIdx % (x2 - x1)
        y = y1 + int(selIdx / (x2 - x1))

        procedure = Gimp.get_pdb().lookup_procedure("gimp-selection-value")
        config = procedure.create_config()
        config.set_property("image", image)
        config.set_property("x", float(x))
        config.set_property("y", float(y))
        result = procedure.run(config)
        value = result.index(1)

        if value > 200:
            coords.append((x, y))
    with open(expfile, "w") as f:
        for co in coords:
            f.write(str(co[0]) + " " + str(co[1]) + "\n")


def getRandomColor(layerCnt):
    uniqueColors = set()
    while len(uniqueColors) < layerCnt:
        red = random.randint(0, 255)
        green = random.randint(0, 255)
        blue = random.randint(0, 255)

        color = (red, green, blue)

        if color not in uniqueColors:
            uniqueColors.add(color)
    return list(uniqueColors)


def createLayers(image, maskFileNoExt, userSelColor, formatBinary, values):
    width, height = image.get_width(), image.get_height()

    idx = 0
    maxLayers = 99999

    parent = Gimp.GroupLayer.new(image)
    parent.set_name(f"Segment Anything - {values.segType}")
    image.insert_layer(parent, None, 0)
    parent.set_opacity(50)

    uniqueColors = getRandomColor(layerCnt=999)

    if image.get_base_type() == Gimp.ImageType.GRAYA_IMAGE:
        layerType = Gimp.ImageType.GRAYA_IMAGE
        userSelColor = [100, 255]
        babl_format = "YA u8"
        pix_size = 2
    else:
        layerType = Gimp.ImageType.RGBA_IMAGE
        babl_format = "RGBA u8"
        pix_size = 4

    while idx < maxLayers:
        filepath = maskFileNoExt + str(idx) + ".seg"
        if exists(filepath):
            print("Creating Layer..", (idx + 1))
            newlayer = Gimp.Layer.new(
                image,
                f"Mask - {values.segType} #{idx + 1}",
                width,
                height,
                layerType,
                100.0,
                Gimp.LayerMode.NORMAL,
            )
            buffer = newlayer.get_buffer()
            image.insert_layer(newlayer, parent, 0)
            newlayer.set_visible(False)

            rect = Gegl.Rectangle.new(0, 0, width, height)

            maskVals = readMaskFile(filepath, formatBinary)
            maskColor = (
                userSelColor
                if userSelColor is not None
                else list(uniqueColors[idx]) + [255]
            )

            mask_color_bytes = bytes(maskColor)
            transparent_pixel = bytes(pix_size)
            row_byte_strings = []
            for row in maskVals:
                row_pixels = []
                for p in row:
                    if p:
                        row_pixels.append(mask_color_bytes)
                    else:
                        row_pixels.append(transparent_pixel)
                row_byte_strings.append(b"".join(row_pixels))
            pixels = b"".join(row_byte_strings)

            buffer.set(rect, babl_format, pixels)

            idx += 1
            newlayer.update(0, 0, width, height)
        else:
            break
    # Gimp.displays_flush()  # turn on only if needed

    return idx


def cleanup(filepathPrefix):
    for f in glob.glob(filepathPrefix + "*"):
        os.remove(f)


def showError(message):
    dialog = Gtk.MessageDialog(
        None,
        Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        Gtk.MessageType.ERROR,
        Gtk.ButtonsType.OK,
        message,
    )

    dialog.run()
    dialog.destroy()


def validateOptions(image, values):
    if values.checkPtPath is None:
        showError(
            "No Segment Anything model configured. Install one with the "
            "gimpsegany installer (or LazyGimp), or set it manually in "
            "Expert Mode."
        )
        return False
    if values.segType == "Text" and not (values.textPrompt or "").strip():
        showError(
            "Empty text prompt. SAM3 needs a short phrase describing what "
            "to segment, e.g. \"car\" or \"red flower\"."
        )
        return False
    if values.segType in {"Selection", "Box"}:
        procedure = Gimp.get_pdb().lookup_procedure("gimp-selection-is-empty")
        config = procedure.create_config()
        config.set_property("image", image)
        result = procedure.run(config)
        isSelEmpty = result.index(1)
        if isSelEmpty:
            showError(
                "No Selection! For the Segmentation Types: "
                + "Selection to work you need "
                + "to select an area on the image"
            )
            return False
    return True


def configLogging(level):
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


class ProgressDialog(Gtk.Dialog):
    """Non-blocking-looking progress window for the bridge subprocess.

    GIMP never calls a plug-in on more than one thread, and there is no
    active GLib main loop iterating while our run() callback is on the
    stack — so simply doing `dialog.show_all()` would draw a dialog that
    never repaints or responds to clicks. We run our own nested
    GLib.MainLoop() to pump GTK events while a background thread waits on
    the actual subprocess; that keeps the window alive, the pulse animating
    and Cancel clickable, all without blocking on the AI workload itself.
    """

    def __init__(self):
        Gtk.Dialog.__init__(
            self,
            title="Segment Anything — working…",
            transient_for=None,
            flags=Gtk.DialogFlags.MODAL,
        )
        self.set_default_size(440, 120)
        self.set_deletable(False)

        box = self.get_content_area()
        box.set_spacing(10)
        box.set_border_width(14)

        self.label = Gtk.Label(label="Starting…")
        self.label.set_line_wrap(True)
        self.label.set_xalign(0)
        box.add(self.label)

        self.bar = Gtk.ProgressBar()
        box.add(self.bar)

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)

        self._pulse_id = GLib.timeout_add(150, self._pulse)
        self.show_all()

    def _pulse(self):
        self.bar.pulse()
        return True

    def set_status(self, text):
        self.label.set_text(text)
        return False

    def teardown(self):
        if self._pulse_id is not None:
            GLib.source_remove(self._pulse_id)
            self._pulse_id = None
        self.destroy()
        return False


def run_bridge_with_progress(cmd):
    """Run the bridge subprocess in a background thread while keeping the
    GIMP UI responsive via a nested main loop. Returns (returncode, cancelled).
    """
    progress = ProgressDialog()
    loop = GLib.MainLoop()
    state = {"cancelled": False, "returncode": None}

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=os.environ.copy(),
    )

    def on_response(dialog, response_id):
        if response_id == Gtk.ResponseType.CANCEL and not state["cancelled"]:
            state["cancelled"] = True
            logging.warning("Segmentation cancelled by the user — terminating bridge")
            try:
                proc.terminate()
            except Exception:
                pass

    progress.connect("response", on_response)

    def reader():
        try:
            for line in iter(proc.stdout.readline, ""):
                line = line.rstrip("\n")
                if line:
                    logging.debug(line)
                    GLib.idle_add(progress.set_status, line)
        finally:
            proc.wait()
            state["returncode"] = proc.returncode
            GLib.idle_add(loop.quit)

    threading.Thread(target=reader, daemon=True).start()
    loop.run()
    progress.teardown()
    return state["returncode"], state["cancelled"]


def run_segmentation(image, values):
    configLogging(logging.DEBUG)
    if not validateOptions(image, values):
        return

    if values.pythonPath is None:
        logging.warning("Warning: python path is None, trying default python executable")
        pythonPath = "python"
    else:
        pythonPath = values.pythonPath

    formatBinary = True
    filePrefix = "__seg__"
    filepathPrefix = os.path.join(tempfile.gettempdir(), filePrefix)
    selFile = filepathPrefix + "sel__.txt"
    maskFileNoExt = filepathPrefix + "mask__"

    segAnyScriptName = "seganybridge.py"

    cleanup(filepathPrefix)

    currDir = os.path.dirname(os.path.realpath(__file__))
    scriptFilepath = os.path.join(currDir, segAnyScriptName)

    ipFilePath = filepathPrefix + next(tempfile._get_candidate_names()) + ".png"

    cmd = [
        pythonPath,
        scriptFilepath,
        values.modelType,
        values.checkPtPath,
        ipFilePath,
        values.segType,
        values.maskType,
        maskFileNoExt,
        str(formatBinary),
    ]

    if values.segType == "Auto":
        cmd.extend(
            [
                values.segRes,
                str(values.cropNLayers),
                str(values.minMaskArea),
                str(values.maxAutoDim),
            ]
        )
    elif values.segType == "Text":
        # SAM3: a noun phrase instead of points/boxes — no GIMP selection
        # needed at all, the whole image is searched for matching concepts.
        cmd.append(values.textPrompt)

    newImage = image.duplicate()
    visLayer = newImage.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)

    procedure = Gimp.get_pdb().lookup_procedure("file-png-export")
    config = procedure.create_config()
    config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    config.set_property("image", newImage)

    gfile = Gio.File.new_for_path(ipFilePath)
    config.set_property("file", gfile)
    config.set_property("interlaced", False)
    config.set_property("compression", 9)
    config.set_property("bkgd", False)
    config.set_property("offs", False)
    config.set_property("phys", False)
    config.set_property("time", False)
    config.set_property("save-transparent", True)
    config.set_property("optimize-palette", False)
    procedure.run(config)

    newImage.delete()

    procedure = Gimp.get_pdb().lookup_procedure("gimp-selection-save")
    config = procedure.create_config()
    config.set_property("image", image)
    result = procedure.run(config)
    channel = result.index(1)

    if values.segType in {"Selection"}:
        exportSelection(image, selFile, values.selPtCnt)
        cmd.append(selFile)
    elif values.segType == "Box":
        procedure = Gimp.get_pdb().lookup_procedure("gimp-selection-bounds")
        config = procedure.create_config()
        config.set_property("image", image)
        result = procedure.run(config)
        x1 = result.index(2)
        y1 = result.index(3)
        x2 = result.index(4)
        y2 = result.index(5)
        cmd.append("sel_place_holder")
        cmd.append(",".join(str(co) for co in [x1, y1, x2, y2]))

    procedure = Gimp.get_pdb().lookup_procedure("gimp-selection-none")
    config = procedure.create_config()
    config.set_property("image", image)
    procedure.run(config)

    # Everything above is GIMP-PDB work and has to happen on this thread.
    # The bridge subprocess is the only genuinely slow, GIMP-independent
    # part — that's what runs in the background while a progress dialog
    # keeps the user informed instead of GIMP looking hung.
    returncode, cancelled = run_bridge_with_progress(cmd)

    if cancelled:
        cleanup(filepathPrefix)
        return

    if returncode != 0:
        showError(
            "Segmentation failed. Check GIMP's Error Console for details "
            "from the Python bridge."
        )
        cleanup(filepathPrefix)
        return

    layerMaskColor = None if values.isRandomColor else values.maskColor
    createLayers(image, maskFileNoExt, layerMaskColor, formatBinary, values)
    cleanup(filepathPrefix)

    if channel is not None:
        procedure = Gimp.get_pdb().lookup_procedure("gimp-image-select-item")
        config = procedure.create_config()
        config.set_property("image", image)
        config.set_property("operation", Gimp.ChannelOps.REPLACE)
        config.set_property("item", channel)
        procedure.run(config)

    logging.debug("Finished creating segments!")


def values_from_config(config, configFilePath):
    """Build a DialogValue from PDB procedure arguments, falling back to the
    persisted/discovered settings for anything left at its GObject default —
    this is what makes the plug-in scriptable (Script-Fu, batch mode, our own
    headless test harness) without ever requiring the interactive dialog."""
    values = DialogValue(configFilePath)
    python_default, models_default = discover_lazygimp_backend()

    def prop(name, fallback):
        try:
            val = config.get_property(name)
        except Exception:
            return fallback
        if val is None or val == "":
            return fallback
        return val

    values.pythonPath = prop("python-path", values.pythonPath or python_default)
    values.checkPtPath = prop(
        "checkpoint-path",
        values.checkPtPath or (models_default[0] if models_default else None),
    )
    values.modelType = prop("model-type", values.modelType)
    values.segType = prop("seg-type", values.segType)
    values.maskType = prop("mask-type", values.maskType)
    values.selPtCnt = int(prop("sel-pt-cnt", values.selPtCnt))
    values.segRes = prop("seg-res", values.segRes)
    values.cropNLayers = int(prop("crop-n-layers", values.cropNLayers))
    values.minMaskArea = int(prop("min-mask-area", values.minMaskArea))
    values.maxAutoDim = int(prop("max-auto-dim", values.maxAutoDim))
    values.textPrompt = prop("text-prompt", values.textPrompt)
    try:
        values.isRandomColor = bool(config.get_property("is-random-color"))
    except Exception:
        pass

    if values.modelType == "Auto":
        values.modelType = "auto"
    else:
        values.modelType = values.modelType.split(" ")[0]
    return values


class SegAnyPlugin(Gimp.PlugIn):
    def do_query_procedures(self):
        return ["seg-any-gimp3"]

    def do_set_i18n(self, procname):
        return False, None, None  # Returning False disables localization

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.seg_any_run, None
        )
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        procedure.set_menu_label("Segment Anything Layers")
        procedure.set_attribution("Shrinivas Kulkarni", "Shrinivas Kulkarni", "2024")
        procedure.add_menu_path("<Image>/Image")

        # PDB arguments mirror the dialog's fields. This makes the plug-in
        # fully scriptable (Script-Fu / Python-Fu / batch mode) and is what
        # lets an automated test harness drive it headlessly, without ever
        # touching the interactive dialog — pass run-mode NONINTERACTIVE and
        # whatever arguments matter; anything left blank/zero falls back to
        # the persisted settings or the LazyGimp auto-discovered backend.
        flags = GObject.ParamFlags.READWRITE
        procedure.add_string_argument("python-path", "Python path", "Interpreter used to run the bridge (blank = auto-discover)", "", flags)
        procedure.add_string_argument("checkpoint-path", "Checkpoint path", "SAM checkpoint file (blank = auto-discover)", "", flags)
        procedure.add_string_argument("model-type", "Model type", "auto/vit_h/vit_l/vit_b/sam2_hiera_*/sam3", "Auto", flags)
        procedure.add_string_argument("seg-type", "Segmentation type", "Auto, Box, Selection, or Text (SAM3)", "Auto", flags)
        procedure.add_string_argument("text-prompt", "Text prompt", "Noun phrase to segment, SAM3 only (e.g. \"car\")", "", flags)
        procedure.add_string_argument("mask-type", "Mask type", "Multiple or Single", "Multiple", flags)
        procedure.add_int_argument("sel-pt-cnt", "Selection points", "Sample points for Selection mode", 1, 1000, 10, flags)
        procedure.add_string_argument("seg-res", "Auto resolution", "Low, Medium or High", "Medium", flags)
        procedure.add_int_argument("crop-n-layers", "Crop n layers", "0 or 1", 0, 1, 0, flags)
        procedure.add_int_argument("min-mask-area", "Minimum mask area", "Discard masks smaller than this, in pixels² (area, not diameter) — 0 keeps everything", 0, 10_000_000, 0, flags)
        procedure.add_int_argument("max-auto-dim", "Max Auto resolution", "Downscale before Auto segmentation (0 = off)", 0, 8192, 1024, flags)
        procedure.add_boolean_argument("is-random-color", "Random mask color", "Use a random color per mask layer", True, flags)

        return procedure

    def seg_any_run(self, procedure, run_mode, image, drawables, config, data):
        scriptDir = os.path.dirname(os.path.abspath(__file__))
        configFilePath = os.path.join(scriptDir, "segany_settings.json")

        if run_mode == Gimp.RunMode.INTERACTIVE:
            boxPathDict = getPathDict(image)
            dialog = OptionsDialog(image, boxPathDict)
            response = dialog.run()

            if response == Gtk.ResponseType.OK:
                values = dialog.get_values()
                image.undo_group_start()
                run_segmentation(image, values)
                image.undo_group_end()

            dialog.destroy()
        else:
            # NONINTERACTIVE / RUN-WITH-LAST-VALS: no dialog, read everything
            # from the PDB config (with auto-discovery/persisted settings as
            # fallback). This is what the headless test harness drives.
            values = values_from_config(config, configFilePath)
            image.undo_group_start()
            run_segmentation(image, values)
            image.undo_group_end()

        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


Gimp.main(SegAnyPlugin.__gtype__, sys.argv)
