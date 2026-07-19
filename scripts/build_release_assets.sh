#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/build_release_assets.sh <version> — assemble everything a GitHub
# release ships, under dist/ (same design as LazyGimp's):
#
#   gimpsam.pyz                 single-file zipapp of the headless CLI —
#                               runs anywhere:  python3 gimpsam.pyz status
#   gimpsam-linux-x86_64        PyInstaller binary of the Tk wizard
#                               (installer.py) — zero deps, Linux x86_64
#   gimpsam-src.zip             the source bundle (gimpsam/ package,
#                               installer.py wizard, plug-in files) — this
#                               is also what LazyGimp vendors at build time
#   gimpsam-<version>-src.zip   the same zip, versioned
#   gimp-segany-gimp3.zip       just the GIMP 3 plug-in folder (the
#                               historical asset name — kept stable)
#   checksums.txt               SHA-256 of every asset
#
# Invoked by semantic-release (@semantic-release/exec, see .releaserc) and
# by the CI dry run. Requires: python3 (+python3-tk for a useful binary),
# pyinstaller, zip.
#
# STAGE_ONLY=1 skips the PyInstaller step (the slow one); everything else
# still runs — the pre-push git hook uses this.
# ---------------------------------------------------------------------------
set -euo pipefail

VERSION="${1:?usage: build_release_assets.sh <version>}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)"
DIST="${ROOT}/dist"
STAGE_ONLY="${STAGE_ONLY:-0}"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

rm -rf "$DIST"
mkdir -p "$DIST"

# --- stage the source tree, stamped with the release version ---------------
BUNDLE="${STAGE}/gimpsam"
mkdir -p "$BUNDLE"
cp -a "${ROOT}/gimpsam" "${ROOT}/installer.py" \
      "${ROOT}/seganyplugin.py" "${ROOT}/seganybridge.py" \
      "${ROOT}/seganyplugin_GIMP2.py" "${ROOT}/seganybridge_GIMP2_SAM1.py" \
      "$BUNDLE/"

copy_first() { # <dest-name> <candidate>...
  local dest="$1" candidate
  shift
  for candidate in "$@"; do
    if [[ -e "${ROOT}/${candidate}" ]]; then
      cp -a "${ROOT}/${candidate}" "${BUNDLE}/${dest}"
      return 0
    fi
  done
  echo "error: none of the candidates for '${dest}' exist: $*" >&2
  exit 1
}
copy_first README.md docs/README.md README.md
copy_first LICENSE docs/LICENSE LICENSE

find "$BUNDLE" -name '__pycache__' -type d -exec rm -rf {} +

sed -i "s/^__version__ = .*/__version__ = \"${VERSION}\"/" \
  "${BUNDLE}/gimpsam/__init__.py"

# --- 1. zipapp: the headless CLI as one .pyz file --------------------------
PYZ_STAGE="${STAGE}/pyz"
mkdir -p "$PYZ_STAGE"
cp -a "${BUNDLE}/gimpsam" "$PYZ_STAGE/"
python3 -m zipapp "$PYZ_STAGE" \
  --main "gimpsam.cli:main" \
  --python "/usr/bin/env python3" \
  --output "${DIST}/gimpsam.pyz" \
  --compress
chmod +x "${DIST}/gimpsam.pyz"

# --- 2. PyInstaller: the Tk wizard as a self-contained Linux binary --------
[[ "$STAGE_ONLY" == "1" ]] || pyinstaller --onefile --clean --noconfirm \
  --name "gimpsam-linux-x86_64" \
  --distpath "$DIST" \
  --workpath "${STAGE}/pyi-build" \
  --specpath "${STAGE}/pyi-spec" \
  --paths "$BUNDLE" \
  --hidden-import tkinter \
  --collect-submodules PIL \
  "${BUNDLE}/installer.py"

# --- 3. source zip: everything needed to run either entry point ------------
(cd "$STAGE" && zip -qr "${DIST}/gimpsam-src.zip" gimpsam \
  -x 'gimpsam/gimpsam/__pycache__/*')
cp "${DIST}/gimpsam-src.zip" "${DIST}/gimpsam-${VERSION}-src.zip"

# --- 4. the plug-in folder alone, under its historical asset name ----------
PLUGIN_STAGE="${STAGE}/plugin"
mkdir -p "${PLUGIN_STAGE}/seganyplugin"
cp -a "${ROOT}/seganyplugin.py" "${ROOT}/seganybridge.py" "${PLUGIN_STAGE}/seganyplugin/"
(cd "$PLUGIN_STAGE" && zip -qr "${DIST}/gimp-segany-gimp3.zip" seganyplugin)

(cd "$DIST" && sha256sum -- * >checksums.txt)

echo "release assets for v${VERSION}:"
ls -l "$DIST"
