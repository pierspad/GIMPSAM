#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# tools/headless_e2e.sh — drives the REAL installed plug-in through real
# GIMP in batch mode (no UI, no clicking required). This is what proves the
# whole pipeline works end-to-end: GIMP PDB dispatch -> seganyplugin.py's
# NONINTERACTIVE path -> the async progress dialog / nested main loop ->
# the seganybridge.py subprocess -> mask layers actually created.
#
# It does NOT replace tools/bench_bridge.py (which is faster and checks
# correctness numerically); this script is the one that would have caught
# the original bug report ("nothing happens, GIMP just freezes") because it
# exercises the exact code path a real user hits.
#
# Usage:
#   ./tools/headless_e2e.sh [/path/to/seganyplugin/dir]
#
# Exit code 0 iff GIMP ran the plug-in to completion within the timeout and
# produced at least one mask layer.
# ---------------------------------------------------------------------------
set -uo pipefail

PLUGIN_DIR="${1:-$HOME/.config/GIMP/3.2/plug-ins/seganyplugin}"
TIMEOUT_S="${SEGANY_E2E_TIMEOUT:-120}"
WORKDIR="$(mktemp -d /tmp/segany_e2e.XXXXXX)"
trap 'rm -rf "$WORKDIR"' EXIT

TEST_IMG="${WORKDIR}/test_img.png"
LOG="${WORKDIR}/gimp.log"

if [[ ! -f "${PLUGIN_DIR}/seganyplugin.py" ]]; then
  echo "[FAIL] plug-in not found at ${PLUGIN_DIR} — install it first" >&2
  exit 1
fi

python3 - "$TEST_IMG" <<'PY'
import sys
from PIL import Image, ImageDraw
img = Image.new("RGB", (1280, 800), (240, 240, 240))
d = ImageDraw.Draw(img)
d.ellipse((450, 220, 830, 580), fill=(200, 30, 30))
img.save(sys.argv[1])
PY

SCRIPT_FU="
(let* ((image (car (gimp-file-load RUN-NONINTERACTIVE \"${TEST_IMG}\" \"test_img.png\")))
       (drawable (car (gimp-image-get-selected-drawables image))))
  (gimp-image-select-rectangle image CHANNEL-OP-REPLACE 450 220 380 360)
  (seg-any-gimp3 RUN-NONINTERACTIVE image drawable
                 \"\" \"\" \"auto\" \"Box\" \"Single\"
                 10 \"Medium\" 0 0 1024 FALSE)
  (gimp-image-flatten image)
  (gimp-image-delete image)
  (gimp-quit 0))
"

echo "[info] running GIMP headless (timeout ${TIMEOUT_S}s)..." >&2
timeout "${TIMEOUT_S}" gimp -i --batch-interpreter=plug-in-script-fu-eval \
  -b "${SCRIPT_FU}" >"${LOG}" 2>&1
rc=$?

if ((rc == 124)); then
  echo "[FAIL] GIMP did not finish within ${TIMEOUT_S}s — this is the freeze bug." >&2
  tail -n 40 "${LOG}" >&2
  exit 1
fi

if grep -q "Finished creating segments" "${LOG}" && grep -q "Creating Layer" "${LOG}"; then
  elapsed="$(grep -oP 'total \K[0-9.]+(?=s\))' "${LOG}" | tail -n1)"
  echo "[PASS] headless run created mask layer(s) in ${elapsed:-?}s"
  exit 0
fi

echo "[FAIL] plug-in ran but did not report success — see log:" >&2
tail -n 40 "${LOG}" >&2
exit 1
