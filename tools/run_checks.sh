#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# tools/run_checks.sh — single entry point for the observability harness.
#
# Runs both layers of check and prints one pass/fail line per check, so an
# agent (or a human) can poll this instead of eyeballing GIMP:
#   1. bench_bridge.py  — direct, fast, numeric correctness (IoU) + speed
#   2. headless_e2e.sh  — the real plug-in through real GIMP batch mode
#
# Usage:
#   ./tools/run_checks.sh --python /path/to/venv/python3 --checkpoint /path/to/model.pth
# ---------------------------------------------------------------------------
set -uo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PYTHON_BIN=""
CHECKPOINT=""
SKIP_E2E=0

while (($#)); do
  case "$1" in
    --python) PYTHON_BIN="$2"; shift ;;
    --checkpoint) CHECKPOINT="$2"; shift ;;
    --skip-e2e) SKIP_E2E=1 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

# Auto-discover the LazyGimp backend if not given explicitly.
if [[ -z "$PYTHON_BIN" ]]; then
  cand="$HOME/.local/share/lazygimp/segany/venv/bin/python3"
  [[ -x "$cand" ]] && PYTHON_BIN="$cand"
fi
if [[ -z "$CHECKPOINT" ]]; then
  models_dir="$HOME/.local/share/lazygimp/segany/models"
  [[ -d "$models_dir" ]] && CHECKPOINT="$(find "$models_dir" -maxdepth 1 -type f \( -name '*.pth' -o -name '*.pt' -o -name '*.safetensors' \) | head -n1)"
fi

if [[ -z "$PYTHON_BIN" || -z "$CHECKPOINT" ]]; then
  echo "[FAIL] could not find a SAM backend — pass --python and --checkpoint explicitly" >&2
  exit 1
fi

echo "== 1/2: bench_bridge.py (direct, fast) =="
overall=0
python3 "${HERE}/bench_bridge.py" --python "$PYTHON_BIN" --checkpoint "$CHECKPOINT" || overall=1

echo
echo "== 2/2: headless_e2e.sh (real GIMP batch mode) =="
if ((SKIP_E2E)); then
  echo "[skip] --skip-e2e"
else
  if command -v gimp >/dev/null 2>&1; then
    "${HERE}/headless_e2e.sh" || overall=1
  else
    echo "[skip] gimp not on PATH"
  fi
fi

echo
if ((overall == 0)); then
  echo "[PASS] all checks green"
else
  echo "[FAIL] see output above"
fi
exit "$overall"
