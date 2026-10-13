#!/bin/sh
# Build on Ubuntu 22.04, whose libmpv and glibc set the AppImage baseline.
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$root"

if ! grep -q '^VERSION_ID="22.04"$' /etc/os-release; then
    echo "Build the Linux AppImage on Ubuntu 22.04" >&2
    exit 1
fi
python=${VPLAYER_PYTHON:-python3.12}
for tool in "$python" linuxdeploy linuxdeploy-plugin-qt appimagetool; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "Missing AppImage build prerequisite: $tool" >&2
        exit 1
    fi
done
if [ -z "${QMAKE:-}" ]; then
    if command -v qmake6 >/dev/null 2>&1; then
        QMAKE=$(command -v qmake6)
    else
        echo "Install qmake6 or provide the Qt plugin's QMAKE path" >&2
        exit 1
    fi
fi
if ! command -v "$QMAKE" >/dev/null 2>&1; then
    echo "Qt plugin qmake not found: $QMAKE" >&2
    exit 1
fi
export QMAKE
if ! ldconfig -p | grep -q 'libmpv.so.1 '; then
    echo "Install Ubuntu's libmpv1 before building the AppImage" >&2
    exit 1
fi
"$python" scripts/package.py
