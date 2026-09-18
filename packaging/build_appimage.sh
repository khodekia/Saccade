#!/usr/bin/env bash
# Build a portable AppImage for Saccade.
# Usage:  bash packaging/build_appimage.sh   (from the project root)
# Result: packaging/dist/Saccade-<version>-x86_64.AppImage
#
# The script bundles the Python sources plus the Qt/PyMuPDF wheels into an
# AppDir, then wraps it with appimagetool.  appimagetool is downloaded to
# packaging/.tools/ on first run (it is not packaged with the repo).

set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' saccade/__init__.py)"
ARCH="$(uname -m)"
APP="Saccade"
TOOLS="packaging/.tools"
APPDIR="packaging/build/${APP}.AppDir"
DEPS="packaging/build/deps"

if [ "$ARCH" != "x86_64" ]; then
  echo "!! This script is written for x86_64 (detected: $ARCH)." >&2
  echo "!! Fetch the matching appimagetool from https://github.com/AppImage/appimagetool/releases and re-run." >&2
fi

echo "==> Building $APP $VERSION AppImage ($ARCH)"

# --- 1. appimagetool ------------------------------------------------------ #
APPIMAGETOOL="$TOOLS/appimagetool-${ARCH}.AppImage"
if [ ! -x "$APPIMAGETOOL" ]; then
  mkdir -p "$TOOLS"
  URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
  echo "==> Downloading appimagetool"
  curl -fL --retry 3 -o "$APPIMAGETOOL" "$URL" \
    || wget -O "$APPIMAGETOOL" "$URL"
  chmod +x "$APPIMAGETOOL"
fi

# --- 2. clean AppDir ------------------------------------------------------ #
rm -rf "$APPDIR"
mkdir -p \
  "$APPDIR/usr/bin" \
  "$APPDIR/usr/lib/saccade" \
  "$APPDIR/usr/share/applications" \
  "$APPDIR/usr/share/icons/hicolor/scalable/apps" \
  "$APPDIR/usr/share/metainfo"

# --- 3. payload ----------------------------------------------------------- #
cp -r saccade "$APPDIR/usr/lib/saccade/"
find "$APPDIR/usr/lib/saccade" -name '__pycache__' -type d -exec rm -rf {} +

# Third-party runtime dependencies: PyQt6 (with its own Qt6 runtime + plugins)
# and PyMuPDF.  Both ship abi3 wheels, so the bundle works with whatever
# Python >= 3.10 the host provides and never touches the distro's Qt packages.
if [ ! -f "$DEPS/.stamp" ]; then
  echo "==> Fetching the PyQt6 + PyMuPDF wheels (network needed once)"
  rm -rf "$DEPS"
  mkdir -p "$DEPS"
  PIPPY="python3"
  [ -x .venv/bin/python ] && PIPPY=".venv/bin/python"
  "$PIPPY" -m pip install --quiet --upgrade --target "$DEPS" \
      --no-compile --only-binary=:all: "PyQt6>=6.5" "PyMuPDF>=1.23" || {
    echo "!! Could not download the PyQt6/PyMuPDF wheels." >&2
    echo "!! Connect to the internet and re-run; or pre-fill $DEPS with" >&2
    echo "!! 'pip install --target $DEPS PyQt6 PyMuPDF' output." >&2
    exit 1
  }
  touch "$DEPS/.stamp"
fi

cp -r "$DEPS" "$APPDIR/usr/lib/saccade/lib"
rm -f "$APPDIR/usr/lib/saccade/lib/.stamp"
find "$APPDIR/usr/lib/saccade/lib" -name '__pycache__' -type d \
  -exec rm -rf {} + 2>/dev/null || true

# --- 4. launcher + desktop entry ------------------------------------------ #
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/bash
# Saccade AppRun: locate a system Python and run the app against the wheels
# bundled inside this AppImage.
HERE="$(dirname "$(readlink -f "$0")")"
LIB="$HERE/usr/lib/saccade/lib"

PY=""
for candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PY="$(command -v "$candidate")"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "Saccade needs Python 3.10 or newer, but python3 was not found." >&2
  exit 1
fi

# PYTHONPATH is searched before the system site-packages, so the bundled
# PyQt6/PyMuPDF win over anything the host happens to have installed.
export PYTHONPATH="$LIB:$HERE/usr/lib/saccade${PYTHONPATH:+:$PYTHONPATH}"
export QT_PLUGIN_PATH="$LIB/PyQt6/Qt6/plugins"
export QT_QPA_PLATFORM_PLUGIN_PATH="$LIB/PyQt6/Qt6/plugins/platforms"

exec "$PY" -m saccade "$@"
EOF
chmod 755 "$APPDIR/AppRun"

ln -sf usr/lib/saccade/saccade "$APPDIR/usr/bin/saccade" 2>/dev/null || true
install -Dm644 packaging/saccade.desktop \
  "$APPDIR/usr/share/applications/saccade.desktop"
install -Dm644 packaging/saccade.desktop "$APPDIR/saccade.desktop"
install -Dm644 packaging/saccade.svg \
  "$APPDIR/usr/share/icons/hicolor/scalable/apps/saccade.svg"
cp packaging/saccade.svg "$APPDIR/saccade.svg"

# --- 5. build ------------------------------------------------------------- #
mkdir -p packaging/dist
OUT="packaging/dist/Saccade-${VERSION}-${ARCH}.AppImage"
ARCH="$ARCH" "$APPIMAGETOOL" --appimage-extract-and-run \
  --no-appstream "$APPDIR" "$OUT" || \
ARCH="$ARCH" "$APPIMAGETOOL" "$APPDIR" "$OUT"

chmod +x "$OUT"
echo "==> Done: $OUT"
ls -la "$OUT"