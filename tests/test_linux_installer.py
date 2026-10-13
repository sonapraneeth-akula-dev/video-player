import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

LINUX = Path(__file__).resolve().parents[1] / "packaging" / "linux"
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux desktop installer")


def run_install(kit: Path, home: Path, *args: str, tools: Path | None = None):
    env = {**os.environ, "HOME": str(home)}
    if tools is not None:
        env["PATH"] = f"{tools}{os.pathsep}{env['PATH']}"
        env["CACHE_LOG"] = str(home / "cache.log")
    return subprocess.run(
        ["sh", str(kit / "install.sh"), *args], env=env, capture_output=True, text=True, check=False,
    )


def test_linux_install_upgrade_uninstall_preserves_unrelated_files(tmp_path):
    home = tmp_path / "user & with spaces"
    home.mkdir()
    kit = tmp_path / "kit"
    kit.mkdir()
    for name in ("install.sh", "vplayer.desktop", "vplayer-new-window.desktop", "vplayer.png"):
        shutil.copy2(LINUX / name, kit / name)
    image = kit / "VPlayer-test.AppImage"
    image.write_bytes(b"first image")
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("update-desktop-database", "gtk-update-icon-cache"):
        tool = tools / name
        tool.write_text(f'#!/bin/sh\nprintf "%s\\n" {name} >> "$CACHE_LOG"\n', encoding="utf-8")
        tool.chmod(0o755)

    base = home / ".local"
    bin_dir = base / "bin"
    apps = base / "share" / "applications"
    icons = base / "share" / "icons" / "hicolor" / "256x256" / "apps"
    for directory in (bin_dir, apps, icons):
        directory.mkdir(parents=True)
        (directory / "keep.txt").write_text("unrelated", encoding="utf-8")

    assert run_install(kit, home, "--uninstall", tools=tools).returncode == 0
    assert run_install(kit, home, "unexpected", tools=tools).returncode == 2
    installed = run_install(kit, home, tools=tools)
    assert installed.returncode == 0, installed.stderr
    assert "Note: ~/.local/bin is not on PATH" in installed.stdout
    assert (bin_dir / "vplayer").read_bytes() == b"first image"
    assert (base / "share" / "vplayer" / "installed").is_file()
    desktop = (apps / "vplayer.desktop").read_text(encoding="utf-8")
    new_window = (apps / "vplayer-new-window.desktop").read_text(encoding="utf-8")
    assert f'Exec="{bin_dir / "vplayer"}" %F' in desktop
    assert f'Exec="{bin_dir / "vplayer"}" --new-window %F' in new_window
    assert "NoDisplay=true" in new_window
    assert next(line for line in desktop.splitlines() if line.startswith("MimeType=")) == next(
        line for line in new_window.splitlines() if line.startswith("MimeType=")
    )
    png = (icons / "vplayer.png").read_bytes()
    assert png.startswith(b"\x89PNG") and (int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")) == (256, 256)

    image.write_bytes(b"upgraded image")
    old_icon = base / "share" / "icons" / "hicolor" / "scalable" / "apps" / "vplayer.svg"
    old_icon.parent.mkdir(parents=True)
    old_icon.write_text("previous managed icon", encoding="utf-8")
    assert run_install(kit, home, tools=tools).returncode == 0
    assert (bin_dir / "vplayer").read_bytes() == b"upgraded image"
    assert not old_icon.exists()
    removed = run_install(kit, home, "--uninstall", tools=tools)
    assert removed.returncode == 0, removed.stderr
    for path in (bin_dir / "vplayer", apps / "vplayer.desktop", apps / "vplayer-new-window.desktop",
                 icons / "vplayer.png", base / "share" / "vplayer" / "installed"):
        assert not path.exists(), path
    for directory in (bin_dir, apps, icons):
        assert (directory / "keep.txt").read_text(encoding="utf-8") == "unrelated"
    assert (home / "cache.log").read_text(encoding="utf-8").splitlines() == [
        "update-desktop-database", "gtk-update-icon-cache",
        "update-desktop-database", "gtk-update-icon-cache",
        "update-desktop-database", "gtk-update-icon-cache",
    ]


def test_linux_uninstall_and_install_leave_unmanaged_files_untouched(tmp_path):
    home = tmp_path / "home"
    kit = tmp_path / "kit"
    kit.mkdir()
    for name in ("install.sh", "vplayer.desktop", "vplayer-new-window.desktop", "vplayer.png"):
        shutil.copy2(LINUX / name, kit / name)
    (kit / "VPlayer-test.AppImage").write_bytes(b"image")
    unmanaged = home / ".local" / "bin" / "vplayer"
    unmanaged.parent.mkdir(parents=True)
    unmanaged.write_bytes(b"keep this")
    assert run_install(kit, home, "--uninstall").returncode == 0
    refused = run_install(kit, home)
    assert refused.returncode == 1
    assert "unmanaged file" in refused.stderr
    assert unmanaged.read_bytes() == b"keep this"
    assert not (home / ".local" / "share" / "vplayer" / "installed").exists()


def test_linux_install_refuses_incomplete_archive_before_writing_stamp(tmp_path):
    home = tmp_path / "home"
    kit = tmp_path / "kit"
    kit.mkdir()
    shutil.copy2(LINUX / "install.sh", kit / "install.sh")
    (kit / "VPlayer-test.AppImage").write_bytes(b"image")
    result = run_install(kit, home)
    assert result.returncode == 1
    assert "Missing VPlayer installation asset" in result.stderr
    assert not (home / ".local" / "share" / "vplayer" / "installed").exists()
