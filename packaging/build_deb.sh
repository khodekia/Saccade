#!/usr/bin/env bash
# Build a Debian .deb for Saccade.
# Usage:  bash packaging/build_deb.sh   (from the project root)
# Result: packaging/dist/saccade_<version>_all.deb

set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' saccade/__init__.py)"
PKG="saccade"
DEBVER="${VERSION}-1"
STAGE="packaging/build/${PKG}_${DEBVER}_all"

echo "==> Building ${PKG} ${DEBVER}"
rm -rf packaging/build
mkdir -p \
  "$STAGE/DEBIAN" \
  "$STAGE/usr/lib/python3/dist-packages" \
  "$STAGE/usr/bin" \
  "$STAGE/usr/share/applications" \
  "$STAGE/usr/share/icons/hicolor/scalable/apps" \
  "$STAGE/usr/share/doc/$PKG" \
  "$STAGE/usr/share/licenses/$PKG"

# --- control file ------------------------------------------------------- #
INSTALLED_KB="$(du -sk saccade | cut -f1)"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: saccade
Version: $DEBVER
Section: office
Priority: optional
Architecture: all
Installed-Size: $INSTALLED_KB
Depends: python3 (>= 3.9), python3-pyqt6, python3-fitz
Recommends: poppler-utils
Suggests: python3-pypdf
Maintainer: Kiavash <kiavash@users.noreply.github.com>
Homepage: https://github.com/khodekia/saccade
Description: PDF reader with bionic-reading fixations
 Saccade re-flows PDF book text and bolds the first part of every
 word, guiding the eye from fixation to fixation. Includes a chapter
 sidebar, bookmarks, full-text search, day and night themes, and
 adjustable fixation strength.
EOF

# --- launcher ----------------------------------------------------------- #
cat > "$STAGE/usr/bin/saccade" <<'EOF'
#!/usr/bin/python3
"""Saccade command-line launcher."""
import sys

from saccade.app import main

if __name__ == "__main__":
    sys.exit(main())
EOF
chmod 755 "$STAGE/usr/bin/saccade"

# --- payload ------------------------------------------------------------ #
cp -r saccade "$STAGE/usr/lib/python3/dist-packages/"
find "$STAGE/usr/lib/python3/dist-packages" -name '__pycache__' -type d \
  -exec rm -rf {} +
find "$STAGE/usr/lib/python3/dist-packages" -name '*.py' \
  -exec python3 -m compileall -q {} +

install -Dm644 packaging/saccade.desktop \
  "$STAGE/usr/share/applications/saccade.desktop"
install -Dm644 packaging/saccade.svg \
  "$STAGE/usr/share/icons/hicolor/scalable/apps/saccade.svg"
install -Dm644 README.md "$STAGE/usr/share/doc/$PKG/README.md"
install -Dm644 LICENSE "$STAGE/usr/share/licenses/$PKG/LICENSE"
gzip -n -9 -c README.md > "$STAGE/usr/share/doc/$PKG/changelog.gz" 2>/dev/null || true

# --- validate + build --------------------------------------------------- #
desktop-file-validate "$STAGE/usr/share/applications/saccade.desktop"
mkdir -p packaging/dist
fakeroot dpkg-deb --build --root-owner-group "$STAGE" \
  "packaging/dist/${PKG}_${DEBVER}_all.deb"

echo "==> Done: packaging/dist/${PKG}_${DEBVER}_all.deb"
dpkg-deb -I "packaging/dist/${PKG}_${DEBVER}_all.deb"
