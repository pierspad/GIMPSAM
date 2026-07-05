#!/usr/bin/env python3
"""Observability harness for seganybridge.py — no GIMP required.

Generates a synthetic image with a KNOWN shape (so we have ground truth),
drives seganybridge.py exactly like the GIMP plug-in does (same argv shape),
and checks two things automatically:

  1. correctness — for Box mode, does the produced mask's bounding box line
     up with the box we asked it to segment (IoU against the known shape)?
  2. speed — how long did it take, and did progress lines actually stream
     out while it ran (regression guard against the "silent for minutes"
     freeze bug)?

Usage:
  python3 tools/bench_bridge.py --python /path/to/venv/python3 \\
      --checkpoint /path/to/sam_vit_b_01ec64.pth [--auto] [--max-auto-dim 1024]

Exit code is 0 iff every check passes — this is what an agent (or CI) should
poll instead of eyeballing terminal output.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import tempfile
import time

import numpy as np

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("This harness needs Pillow: pip install pillow", file=sys.stderr)
    raise

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(os.path.dirname(HERE), "seganybridge.py")

# Ground-truth shape baked into the synthetic test image.
ELLIPSE_BOX = (700, 340, 1220, 740)  # x1, y1, x2, y2
RECT_BOX = (100, 100, 400, 300)


def make_test_image(path, size=(1920, 1080)):
    img = Image.new("RGB", size, (240, 240, 240))
    d = ImageDraw.Draw(img)
    d.ellipse(ELLIPSE_BOX, fill=(200, 30, 30))
    d.rectangle(RECT_BOX, fill=(30, 120, 200))
    img.save(path)
    return path


def read_mask(path):
    with open(path, "rb") as f:
        data = f.read()
    rows = struct.unpack(">I", data[0:4])[0]
    cols = struct.unpack(">I", data[4:8])[0]
    bits = np.frombuffer(data[8:], dtype=np.uint8)
    arr = np.unpackbits(bits, bitorder="little")[: rows * cols].reshape(rows, cols)
    return arr.astype(bool)


def iou_with_box(mask, box):
    x1, y1, x2, y2 = box
    gt = np.zeros_like(mask)
    gt[y1:y2, x1:x2] = True
    inter = np.logical_and(mask, gt).sum()
    union = np.logical_or(mask, gt).sum()
    return inter / union if union else 0.0


def run_bridge(python_bin, checkpoint, argv_tail, log_path):
    cmd = [python_bin, BRIDGE, "auto", checkpoint] + argv_tail
    t0 = time.time()
    progress_lines = 0
    with open(log_path, "w") as log:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            log.write(line)
            if line.startswith("[progress]") or line.startswith("[stage]"):
                progress_lines += 1
        proc.wait()
    elapsed = time.time() - t0
    return {
        "returncode": proc.returncode,
        "elapsed_s": round(elapsed, 1),
        "progress_lines": progress_lines,
    }


def check_box(python_bin, checkpoint, tmpdir, image_path):
    sel_file = os.path.join(tmpdir, "sel_place_holder")
    save_prefix = os.path.join(tmpdir, "box_mask_")
    log_path = os.path.join(tmpdir, "box.log")
    argv_tail = [
        image_path,
        "Box",
        "Single",
        save_prefix,
        "True",
        sel_file,
        ",".join(str(v) for v in ELLIPSE_BOX),
    ]
    result = run_bridge(python_bin, checkpoint, argv_tail, log_path)
    mask_path = save_prefix + "0.seg"
    ok = result["returncode"] == 0 and os.path.exists(mask_path)
    iou = None
    if ok:
        mask = read_mask(mask_path)
        iou = float(round(iou_with_box(mask, ELLIPSE_BOX), 3))
        ok = iou >= 0.7
    result.update({"check": "box", "iou": iou, "pass": bool(ok)})
    return result


def check_auto(python_bin, checkpoint, tmpdir, image_path, max_auto_dim):
    save_prefix = os.path.join(tmpdir, "auto_mask_")
    log_path = os.path.join(tmpdir, "auto.log")
    argv_tail = [
        image_path,
        "Auto",
        "Multiple",
        save_prefix,
        "True",
        "Medium",
        "0",
        "0",
        str(max_auto_dim),
    ]
    result = run_bridge(python_bin, checkpoint, argv_tail, log_path)
    masks = sorted(
        f for f in os.listdir(tmpdir) if f.startswith("auto_mask_") and f.endswith(".seg")
    )
    ok = result["returncode"] == 0 and len(masks) > 0
    result.update({"check": "auto", "num_masks": len(masks), "pass": bool(ok)})
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--python", required=True, help="python3 inside the SAM venv")
    ap.add_argument("--checkpoint", required=True, help="path to a .pth/.pt checkpoint")
    ap.add_argument("--max-auto-dim", type=int, default=1024)
    ap.add_argument("--skip-auto", action="store_true", help="Box check only (fast)")
    ap.add_argument("--report", default=None, help="write JSON report here")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="segany_bench_") as tmpdir:
        image_path = make_test_image(os.path.join(tmpdir, "test_img.png"))

        results = [check_box(args.python, args.checkpoint, tmpdir, image_path)]
        if not args.skip_auto:
            results.append(
                check_auto(
                    args.python, args.checkpoint, tmpdir, image_path, args.max_auto_dim
                )
            )

    all_ok = all(r["pass"] for r in results)
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"[{status}] {json.dumps(r)}")

    if args.report:
        with open(args.report, "w") as f:
            json.dump(results, f, indent=2)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
