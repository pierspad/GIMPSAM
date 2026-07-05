# GIMPSAM — Segment Anything for GIMP
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://github.com/pierspad/textmerger/blob/main/docs/LICENSE)
### Credits

This project is a hard fork of [Shriinivas/gimpsegany](https://github.com/Shriinivas/gimpsegany) — all the original plugin architecture, the GIMP 3 integration, and SAM1/SAM2 support are their work. **GIMPSAM** is an updated version built on top of that foundation to have support to the latest **SAM 3.1** model with text-based segmentation, an easier installer, optimized parallel performance and better integration with the [LazyGIMP](https://github.com/pierspad/LazyGimp) project.

---

# Quick installer with one command

```bash
curl -fsSL https://raw.githubusercontent.com/pierspad/GIMPSAM/main/installer.py | python3 - --ephemeral
```

### or by cloning the repo

```bash
git clone https://github.com/pierspad/GIMPSAM
cd GIMPSAM
python3 installer.py
```

The installer will and walk you through installing the plug-in, setting up the backend, and downloading the models.

---

If you'd rather do every step yourself:

## Manual configuration


1. **Find GIMP's plug-ins folder.** `Edit > Preferences > Folders > Plug-ins` inside GIMP, or the defaults:
   - Linux: `~/.config/GIMP/3.0/plug-ins/`
   - Windows: `C:\Users\[YourUsername]\AppData\Roaming\GIMP\3.0\plug-ins\`
   - macOS: `~/Library/Application Support/GIMP/3.0/plug-ins/`
2. **Copy the plugin files.** Create a `seganyplugin` folder inside it and copy `seganyplugin.py` and `seganybridge.py` into it. On Linux/macOS, make sure both are executable (`chmod +x seganyplugin.py seganybridge.py`).
3. **Create a Python environment for the backend** (a virtualenv is recommended, e.g. `python3 -m venv ~/.local/share/lazygimp/segany/venv`).
4. **Install PyTorch** for your hardware — CPU wheels from `https://download.pytorch.org/whl/cpu`, or the matching CUDA/ROCm index for a GPU.
5. **Install image dependencies:** `pip install numpy pillow opencv-python-headless`.
6. **Install a SAM backend package**, depending on which model family you want:
   - SAM1: `pip install git+https://github.com/facebookresearch/segment-anything.git`
   - SAM2: `pip install git+https://github.com/facebookresearch/segment-anything-2.git`
   - SAM3: `pip install transformers huggingface_hub` (no separate repo needed — see the SAM3 section below)
7. **Download a checkpoint** — SAM1/SAM2 URLs are listed in `installer.py`'s `MODEL_REGISTRY`; SAM3 requires requesting access on [Hugging Face](https://huggingface.co/facebook/sam3.1) first, then downloading with `huggingface_hub.snapshot_download(repo_id="facebook/sam3.1", local_dir=..., token=...)`.
8. **Verify it works** by running the bridge test at the bottom of this document.
9. Restart GIMP — it only scans the plug-ins folder on startup.

---

## Table of contents

- [Bridge test](#bridge-test)
- [Plugin usage](#plugin-usage)
  - [Options](#options)
  - [Auto segmentation options (SAM1 and SAM2)](#auto-segmentation-options-sam1-and-sam2)
  - [SAM3](#sam3)
  - [Workflow](#workflow)

---

## Bridge test

Sanity-check the backend directly, independent of GIMP:

```bash
/path/to/python3 ./seganybridge.py auto /path/to/checkpoint/sam_vit_l_0b3195.pth
```

A "Success!!" message indicates a working installation. See `tools/bench_bridge.py` and `tools/headless_e2e.sh` for deeper correctness/speed checks.

## Plugin usage

- Open GIMP. Under the "Image" menu, you should see a new submenu called "Segment Anything Layers".
- Open an image file and click on the plugin's menu item to bring up the dialog box.

### Options

- **Python3 Path:** The path to the python3 instance used while running the seganybridge script.
- **Model Type:** The type of the Segment Anything model to use. Can be set to `Auto` to infer from the checkpoint filename (`sam_` prefix for SAM1, `sam2` for SAM2).
- **Checkpoint Path:** The path to the downloaded Segment Anything model checkpoint file (`.pth` or `.safetensors`).
- **Segmentation Type:** The method to be used for segmentation.
  - **Auto:** Automatically segments the entire image (SAM1/SAM2 only).
  - **Box:** Segments objects within a user-drawn rectangular selection.
  - **Selection:** Segments objects based on sample points from a user-drawn selection (SAM1/SAM2 only).
  - **Text:** Describe what to select in a short phrase, e.g. `"car"` (SAM3 only — replaces the options above when a SAM3 model is chosen).
- **Mask Type:**
  - **Multiple:** Creates a separate layer for each potential object.
  - **Single:** Creates a single layer with the mask that has the highest AI probability.
- **Random Mask Color:** If checked, the generated layers will have random colors. Otherwise, a specific color can be chosen.

### Auto segmentation options (SAM1 and SAM2)

- **Segmentation Resolution:** Controls the density of the segmentation grid. Higher values will generate more masks but will be slower.
- **Crop n Layers:** Enables segmentation on smaller, overlapping crops of the image, which can improve accuracy for smaller objects.
- **Minimum Mask Area:** Discards small, irrelevant masks.
- **Max resolution for Auto:** Downscales large images before running Auto segmentation, then upscales the resulting masks back — the biggest lever for speed on CPU, since Auto's cost scales with pixel count.

### SAM3

For SAM3 you will need to request the acces on HuggingFace to download the models.
SAM3 uses `transformers`' own `Sam3Model`/`Sam3Processor` rather than Meta's standalone repo, so it runs on CPU (slowly — expect several seconds per image) without needing Python 3.12+.

### Workflow

1. Select your desired options in the plugin dialog and click "OK".
2. The plugin will create a new layer group with one or more mask layers.
3. Find the mask layer corresponding to the object you want to isolate.
4. Select that layer and use the "Fuzzy Selection" tool to select the mask area.
5. Hide the new layer group and select your original image layer.
6. You can now cut, copy, or perform any other GIMP operation on the selected object.
---

## Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss your ideas.

---

## AI Disclosure

This project was developed with the assistance of Large Language Models, used to support code writing and documentation.

---
## License

This project is licensed under the GPL v3 License — see the [LICENSE](LICENSE) file for details.
