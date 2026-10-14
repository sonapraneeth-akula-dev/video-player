"""Per-user installation and uninstallation for Linux and Windows."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from vplayer import APP_NAME

VIDEO_EXTENSIONS = (
    ".mp4", ".mkv", ".webm", ".mov", ".avi", ".ts", ".m4v", ".wmv", ".flv",
    ".mpg", ".mpeg", ".ogv", ".3gp", ".3g2", ".m2ts", ".mts", ".vob",
)

MIME_TYPES = (
    "video/mp4",
    "video/x-m4v",
    "video/x-matroska",
    "video/webm",
    "video/quicktime",
    "video/x-msvideo",
    "video/avi",
    "video/msvideo",
    "video/mpeg",
    "video/x-mpeg",
    "video/mp2t",
    "video/x-flv",
    "video/x-ms-wmv",
    "video/ogg",
    "video/x-ogm+ogg",
    "video/3gpp",
    "video/3gpp2",
    "video/h264",
    "video/x-h264",
    "video/h265",
    "video/x-theora+ogg",
    "application/x-matroska",
)

_PACKAGING_DIR = Path(__file__).resolve().parents[2] / "packaging"


def _desktop_entry(exec_cmd: str, *, new_window: bool = False) -> str:
    mime_line = ";".join(MIME_TYPES) + ";"
    if new_window:
        return (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={APP_NAME} (new window)\n"
            f"Comment=Open video in a new {APP_NAME} window\n"
            f"Exec={exec_cmd} --new-window %F\n"
            "Icon=vplayer\n"
            "Terminal=false\n"
            "Categories=AudioVideo;Video;Player;\n"
            f"MimeType={mime_line}\n"
            "NoDisplay=true\n"
        )
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Desktop video player for local and SFTP media\n"
        f"Exec={exec_cmd} %F\n"
        "Icon=vplayer\n"
        "Terminal=false\n"
        "Categories=AudioVideo;Video;Player;\n"
        f"MimeType={mime_line}\n"
    )


def _refresh_linux_caches(apps_dir: Path, icons_dir: Path) -> None:
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(apps_dir)], check=False)
    if shutil.which("gtk-update-icon-cache"):
        subprocess.run(["gtk-update-icon-cache", "-q", str(icons_dir)], check=False)


def install_linux(home: Path | None = None, *, set_default: bool = False) -> int:
    home = home or Path(os.environ.get("HOME", str(Path.home())))
    opt_dir = home / ".local" / "opt" / "vplayer"
    bin_dir = home / ".local" / "bin"
    bin_link = bin_dir / "vplayer"
    apps_dir = home / ".local" / "share" / "applications"
    icons_dir = home / ".local" / "share" / "icons" / "hicolor"
    png_icon = icons_dir / "256x256" / "apps" / "vplayer.png"
    svg_icon = icons_dir / "scalable" / "apps" / "vplayer.svg"
    stamp = home / ".local" / "share" / "vplayer" / "installed"

    for directory in (opt_dir, bin_dir, apps_dir, png_icon.parent, svg_icon.parent, stamp.parent):
        directory.mkdir(parents=True, exist_ok=True)

    target_bin = opt_dir / "vplayer"
    appimage = os.environ.get("APPIMAGE")
    if appimage and Path(appimage).is_file():
        shutil.copy2(appimage, target_bin)
        target_bin.chmod(0o755)
    elif getattr(sys, "frozen", False):
        bundle_dir = Path(sys.executable).resolve().parent
        if bundle_dir != opt_dir:
            shutil.copytree(bundle_dir, opt_dir, dirs_exist_ok=True)
        target_bin.chmod(0o755)
    else:
        target_bin.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m vplayer "$@"\n', encoding="utf-8")
        target_bin.chmod(0o755)

    if bin_link.is_symlink() or bin_link.exists():
        bin_link.unlink()
    try:
        bin_link.symlink_to(target_bin)
    except OSError:
        shutil.copy2(target_bin, bin_link)

    linux_assets = _PACKAGING_DIR / "linux"
    if (linux_assets / "vplayer.png").is_file():
        shutil.copy2(linux_assets / "vplayer.png", png_icon)
    if (linux_assets / "vplayer.svg").is_file():
        shutil.copy2(linux_assets / "vplayer.svg", svg_icon)

    quoted = str(bin_link).replace("\\", "\\\\").replace('"', '\\"')
    exec_cmd = f'"{quoted}"'
    (apps_dir / "vplayer.desktop").write_text(_desktop_entry(exec_cmd), encoding="utf-8")
    (apps_dir / "vplayer-new-window.desktop").write_text(
        _desktop_entry(exec_cmd, new_window=True), encoding="utf-8",
    )
    stamp.write_text("VPlayer installer managed\n", encoding="utf-8")
    _refresh_linux_caches(apps_dir, icons_dir)

    if set_default and shutil.which("xdg-mime"):
        for mime in MIME_TYPES:
            subprocess.run(["xdg-mime", "default", "vplayer.desktop", mime], check=False)

    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    if str(bin_dir) not in path_entries:
        print("Note: ~/.local/bin is not on PATH yet; log out and back in to run 'vplayer' from a terminal.")
    print(f"VPlayer installed to {bin_link}")
    return 0


def uninstall_linux(home: Path | None = None) -> int:
    home = home or Path(os.environ.get("HOME", str(Path.home())))
    opt_dir = home / ".local" / "opt" / "vplayer"
    bin_link = home / ".local" / "bin" / "vplayer"
    apps_dir = home / ".local" / "share" / "applications"
    icons_dir = home / ".local" / "share" / "icons" / "hicolor"
    png_icon = icons_dir / "256x256" / "apps" / "vplayer.png"
    svg_icon = icons_dir / "scalable" / "apps" / "vplayer.svg"
    stamp = home / ".local" / "share" / "vplayer" / "installed"

    for path in (
        bin_link,
        apps_dir / "vplayer.desktop",
        apps_dir / "vplayer-new-window.desktop",
        png_icon,
        svg_icon,
        stamp,
    ):
        if path.is_symlink() or path.exists():
            path.unlink()
    if opt_dir.exists():
        shutil.rmtree(opt_dir, ignore_errors=True)
    if stamp.parent.exists():
        try:
            stamp.parent.rmdir()
        except OSError:
            pass
    _refresh_linux_caches(apps_dir, icons_dir)
    print("VPlayer removed.")
    return 0


def _strip_win_path_dir(path_value: str, target_dir: str) -> tuple[str, bool]:
    norm_target = target_dir.rstrip("\\/").lower()
    kept = []
    found = False
    for part in path_value.split(";"):
        if part.strip().rstrip("\\/").lower() == norm_target:
            found = True
        elif part:
            kept.append(part)
    return ";".join(kept), found


def _create_windows_shortcut(shortcut_path: Path, target_path: Path, icon_path: Path | None = None) -> None:
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    ps_script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{str(shortcut_path).replace(chr(39), chr(39)*2)}'); "
        f"$s.TargetPath = '{str(target_path).replace(chr(39), chr(39)*2)}'; "
    )
    if icon_path is not None and icon_path.is_file():
        ps_script += f"$s.IconLocation = '{str(icon_path).replace(chr(39), chr(39)*2)},0'; "
    ps_script += "$s.Save()"
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        check=False, capture_output=True,
    )


def install_windows(install_dir: Path | None = None, *, set_default: bool = False) -> int:
    import winreg

    local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    install_dir = install_dir or (local_app_data / "Programs" / "VPlayer")
    install_dir.mkdir(parents=True, exist_ok=True)

    if getattr(sys, "frozen", False):
        bundle_dir = Path(sys.executable).resolve().parent
        if bundle_dir != install_dir:
            shutil.copytree(bundle_dir, install_dir, dirs_exist_ok=True)
        target_bin = install_dir / "vplayer.exe"
    else:
        target_bin = install_dir / "vplayer.cmd"
        target_bin.write_text(f'@echo off\r\n"{sys.executable}" -m vplayer %*\r\n', encoding="utf-8")

    ico_src = _PACKAGING_DIR / "windows" / "vplayer.ico"
    ico_dst = install_dir / "vplayer.ico"
    if ico_src.is_file():
        shutil.copy2(ico_src, ico_dst)
    icon_ref = ico_dst if ico_dst.is_file() else target_bin

    prog_id = "VPlayer.Video"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{prog_id}") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "VPlayer Video")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{prog_id}\DefaultIcon") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{icon_ref}",0')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{prog_id}\shell\open\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{target_bin}" "%1"')

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\VPlayer\Capabilities") as key:
        winreg.SetValueEx(key, "ApplicationName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(
            key, "ApplicationDescription", 0, winreg.REG_SZ,
            "Desktop video player for local and SFTP media",
        )
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\VPlayer\Capabilities\FileAssociations") as assoc_key:
        for ext in VIDEO_EXTENSIONS:
            winreg.SetValueEx(assoc_key, ext, 0, winreg.REG_SZ, prog_id)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{ext}\OpenWithProgids") as ow_key:
                winreg.SetValueEx(ow_key, prog_id, 0, winreg.REG_SZ, "")
            if set_default:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{ext}") as ext_key:
                    winreg.SetValueEx(ext_key, "", 0, winreg.REG_SZ, prog_id)

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\RegisteredApplications") as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, r"Software\VPlayer\Capabilities")

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as env_key:
        try:
            current_path, _ = winreg.QueryValueEx(env_key, "Path")
        except FileNotFoundError:
            current_path = ""
        _, found = _strip_win_path_dir(current_path, str(install_dir))
        if not found:
            new_path = f"{current_path.rstrip(';')};{install_dir}" if current_path.strip(";") else str(install_dir)
            winreg.SetValueEx(env_key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\VPlayer") as marker_key:
                winreg.SetValueEx(marker_key, "PathAdded", 0, winreg.REG_SZ, "1")
                winreg.SetValueEx(marker_key, "InstallDir", 0, winreg.REG_SZ, str(install_dir))

    appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    start_menu_lnk = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "VPlayer.lnk"
    desktop_lnk = Path.home() / "Desktop" / "VPlayer.lnk"
    _create_windows_shortcut(start_menu_lnk, target_bin, ico_dst)
    _create_windows_shortcut(desktop_lnk, target_bin, ico_dst)

    print(f"VPlayer installed to {install_dir}")
    return 0


def _delete_reg_tree(root, subkey: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _delete_reg_tree(root, f"{subkey}\\{child}")
        winreg.DeleteKey(root, subkey)
    except FileNotFoundError:
        pass


def uninstall_windows(install_dir: Path | None = None) -> int:
    import winreg

    local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    install_dir = install_dir or (local_app_data / "Programs" / "VPlayer")
    prog_id = "VPlayer.Video"

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\VPlayer", 0, winreg.KEY_READ) as marker_key:
            path_added, _ = winreg.QueryValueEx(marker_key, "PathAdded")
    except FileNotFoundError:
        path_added = "0"

    if path_added == "1":
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE,
            ) as env_key:
                current_path, _ = winreg.QueryValueEx(env_key, "Path")
                updated_path, found = _strip_win_path_dir(current_path, str(install_dir))
                if found:
                    winreg.SetValueEx(env_key, "Path", 0, winreg.REG_EXPAND_SZ, updated_path)
        except FileNotFoundError:
            pass

    _delete_reg_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{prog_id}")
    for ext in VIDEO_EXTENSIONS:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, rf"Software\Classes\{ext}\OpenWithProgids", 0, winreg.KEY_WRITE,
            ) as ow_key:
                winreg.DeleteValue(ow_key, prog_id)
        except FileNotFoundError:
            pass

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\RegisteredApplications", 0, winreg.KEY_WRITE,
        ) as reg_apps:
            winreg.DeleteValue(reg_apps, APP_NAME)
    except FileNotFoundError:
        pass

    _delete_reg_tree(winreg.HKEY_CURRENT_USER, r"Software\VPlayer")

    appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    for lnk in (
        appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "VPlayer.lnk",
        Path.home() / "Desktop" / "VPlayer.lnk",
    ):
        if lnk.is_file():
            lnk.unlink()

    if install_dir.exists():
        shutil.rmtree(install_dir, ignore_errors=True)

    print("VPlayer removed.")
    return 0


def run_install(*, set_default: bool = False) -> int:
    if sys.platform == "win32":
        return install_windows(set_default=set_default)
    return install_linux(set_default=set_default)


def run_uninstall() -> int:
    if sys.platform == "win32":
        return uninstall_windows()
    return uninstall_linux()
