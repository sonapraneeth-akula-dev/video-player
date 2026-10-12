#!/bin/sh
# Install (or with --uninstall, remove) the VPlayer AppImage for the current user.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
bin="$HOME/.local/bin/vplayer"
apps="$HOME/.local/share/applications"
icons="$HOME/.local/share/icons/hicolor"
icon="$icons/scalable/apps/vplayer.svg"

refresh() {
    if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database "$apps" || true; fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q "$icons" || true; fi
}

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$bin" "$apps/vplayer.desktop" "$apps/vplayer-new-window.desktop" "$icon"
    refresh
    echo "VPlayer removed."
    exit 0
fi

set -- "$here"/VPlayer-*.AppImage
if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
    echo "Expected exactly one VPlayer-*.AppImage next to install.sh" >&2
    exit 1
fi
mkdir -p "$(dirname "$bin")" "$apps" "$(dirname "$icon")"
install -m 755 "$1" "$bin"
install -m 644 "$here/vplayer.svg" "$icon"

# Desktop-entry quoting of the absolute path, then escaping for the sed replacement.
quoted=$(printf '%s' "$bin" | sed 's/[\\"`$]/\\&/g')
exec_line=$(printf '"%s"' "$quoted" | sed 's/[\\&|]/\\&/g')
sed "s|^Exec=vplayer|Exec=$exec_line|" "$here/vplayer.desktop" > "$apps/vplayer.desktop"
sed -e "s|^Exec=vplayer|Exec=$exec_line --new-window|" -e 's/^Name=VPlayer$/Name=VPlayer (new window)/' \
    -e '$a NoDisplay=true' "$here/vplayer.desktop" > "$apps/vplayer-new-window.desktop"
refresh

case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) echo "Note: ~/.local/bin is not on PATH yet; log out and back in to run 'vplayer' from a terminal." ;;
esac
echo "VPlayer installed to $bin"
