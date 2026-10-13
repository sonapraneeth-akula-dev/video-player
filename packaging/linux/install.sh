#!/bin/sh
# Install (or with --uninstall, remove) the VPlayer AppImage for the current user.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
bin="$HOME/.local/bin/vplayer"
apps="$HOME/.local/share/applications"
icons="$HOME/.local/share/icons/hicolor"
icon="$icons/256x256/apps/vplayer.png"
old_icon="$icons/scalable/apps/vplayer.svg"
stamp="$HOME/.local/share/vplayer/installed"

refresh() {
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$apps" || echo "Warning: desktop cache refresh failed" >&2
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q "$icons" || echo "Warning: icon cache refresh failed" >&2
    fi
}

if [ "${1:-}" = "--uninstall" ]; then
    if [ "$#" -ne 1 ]; then echo "Usage: install.sh [--uninstall]" >&2; exit 2; fi
    if [ ! -f "$stamp" ]; then
        echo "No VPlayer installation managed by this script."
        exit 0
    fi
    rm -f "$bin" "$apps/vplayer.desktop" "$apps/vplayer-new-window.desktop" "$icon" "$old_icon"
    rm -f "$stamp"
    rmdir "$(dirname "$stamp")" 2>/dev/null || true
    refresh
    echo "VPlayer removed."
    exit 0
fi
if [ "$#" -ne 0 ]; then echo "Usage: install.sh [--uninstall]" >&2; exit 2; fi

set -- "$here"/VPlayer-*.AppImage
if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
    echo "Expected exactly one VPlayer-*.AppImage next to install.sh" >&2
    exit 1
fi
for asset in vplayer.desktop vplayer-new-window.desktop vplayer.png; do
    if [ ! -f "$here/$asset" ]; then
        echo "Missing VPlayer installation asset: $asset" >&2
        exit 1
    fi
done
for target in "$bin" "$apps/vplayer.desktop" "$apps/vplayer-new-window.desktop" "$icon"; do
    if [ -e "$target" ] && [ ! -f "$stamp" ]; then
        echo "Refusing to overwrite unmanaged file: $target" >&2
        exit 1
    fi
done
mkdir -p "$(dirname "$bin")" "$apps" "$(dirname "$icon")" "$(dirname "$stamp")"
printf '%s\n' 'VPlayer installer managed' > "$stamp"
install -m 755 "$1" "$bin"
install -m 644 "$here/vplayer.png" "$icon"
if [ -f "$old_icon" ]; then rm -f "$old_icon"; fi

# Desktop-entry quoting of the absolute path, then escaping for the sed replacement.
quoted=$(printf '%s' "$bin" | sed 's/[\\"`$]/\\&/g')
exec_line=$(printf '"%s"' "$quoted" | sed 's/[\\&|]/\\&/g')
sed "s|^Exec=vplayer|Exec=$exec_line|" "$here/vplayer.desktop" > "$apps/vplayer.desktop"
sed "s|^Exec=vplayer|Exec=$exec_line|" "$here/vplayer-new-window.desktop" > "$apps/vplayer-new-window.desktop"
refresh

case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) echo "Note: ~/.local/bin is not on PATH yet; log out and back in to run 'vplayer' from a terminal." ;;
esac
echo "VPlayer installed to $bin"
