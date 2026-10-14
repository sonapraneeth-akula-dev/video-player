import logging
import os
import subprocess
import sys
from io import StringIO
from pathlib import Path
from shutil import copyfile

import pytest
from PySide6.QtWidgets import QApplication

from vplayer import __main__ as entry
from vplayer import __version__
from vplayer.settings import Settings
from vplayer.ui.main_window import MainWindow

MEDIA = Path(__file__).resolve().parent / "media" / "h264_25.mp4"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console API")
@pytest.mark.parametrize(("attached", "error"), ((True, 0), (False, 5), (False, 6)))
def test_console_output_when_packaged_without_stdio(monkeypatch, attached, error):
    class Attach:
        def __call__(self, parent):
            assert parent == 0xFFFFFFFF
            return int(attached)

    class Kernel:
        AttachConsole = Attach()

    outputs = []

    def console_file(path, mode, **options):
        assert (path, mode, options) == ("CONOUT$", "w", {"encoding": "utf-8", "buffering": 1})
        output = StringIO()
        outputs.append(output)
        return output

    with monkeypatch.context() as patch:
        patch.setattr(entry.ctypes, "WinDLL", lambda *args, **kwargs: Kernel())
        patch.setattr(entry.ctypes, "get_last_error", lambda: error)
        patch.setattr(entry, "open", console_file, raising=False)
        patch.setattr(sys, "stdout", None)
        patch.setattr(sys, "stderr", None)
        entry._attach_parent_console()
        if error != 6:
            print("console output")
            assert outputs[0].getvalue() == "console output\n"
            assert len(outputs) == 2
        else:
            assert not outputs


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console API")
def test_console_attachment_surfaces_unexpected_errors(monkeypatch):
    class Attach:
        def __call__(self, _parent):
            return 0

    class Kernel:
        AttachConsole = Attach()

    with monkeypatch.context() as patch:
        patch.setattr(entry.ctypes, "WinDLL", lambda *args, **kwargs: Kernel())
        patch.setattr(entry.ctypes, "get_last_error", lambda: 87)
        patch.setattr(sys, "stdout", None)
        patch.setattr(sys, "stderr", None)
        with pytest.raises(OSError) as failure:
            entry._attach_parent_console()
    assert failure.value.winerror == 87


def test_version_prints_without_starting_qt(capsys, monkeypatch):
    monkeypatch.setattr(entry, "QApplication", lambda argv: pytest.fail("Qt started for --version"))
    with pytest.raises(SystemExit) as exit_status:
        entry.main(["--version"])
    assert exit_status.value.code == 0
    assert capsys.readouterr().out == f"VPlayer {__version__}\n"


@pytest.mark.parametrize(
    ("kind", "file", "expected"),
    (
        ("video", "matrix_h264_mp4.mp4", 0),
        ("audio", "matrix_mp3_mp3.mp3", 0),
        ("video", "missing.mp4", 1),
        ("video", "matrix_mp3_mp3.mp3", 1),
    ),
)
def test_codec_probe_reports_decoding_result(kind, file, expected):
    result = subprocess.run(
        [sys.executable, "-m", "vplayer", "--codec-probe", kind, str(MEDIA.parent / file)],
        capture_output=True, text=True, timeout=40, check=False,
    )
    assert result.returncode == expected, result.stderr


@pytest.mark.parametrize("flags", [[], ["--new-window"]])
def test_cli_opens_relative_file_and_reports_missing_file(qtbot, monkeypatch, tmp_path, flags):
    app = QApplication.instance()
    logger = logging.getLogger("vplayer")
    old_handlers = logger.handlers[:]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(entry, "QApplication", lambda argv: app)
    monkeypatch.setattr(entry.QStandardPaths, "writableLocation", lambda location: str(tmp_path))
    monkeypatch.setattr("vplayer.ui.main_window.Settings", lambda: Settings(tmp_path / "settings.ini"))
    media = tmp_path / MEDIA.name
    copyfile(MEDIA, media)
    relative = os.path.relpath(media, tmp_path)
    second = tmp_path / "second.mp4"
    copyfile(MEDIA, second)
    missing = "missing.mp4"

    def exit_after_show(self):
        windows = [w for w in self.topLevelWidgets() if isinstance(w, MainWindow) and w.isVisible()]
        try:
            assert len(windows) == 1
            playing = windows[0]
            assert playing.statusBar().currentMessage() == "Could not open 1 file(s)"
            qtbot.waitUntil(
                lambda: playing.player.state()["duration"] is not None,
                timeout=10000,
            )
            assert playing.player._uri == str(second)
            assert playing.tabs.count() == 2
            assert {playing.tabs.widget(i).player._uri for i in range(2)} == {str(media), str(second)}
            return 0
        finally:
            for window in windows:
                window.close()

    monkeypatch.setattr(QApplication, "exec", exit_after_show)
    try:
        assert entry.main([*flags, relative, str(second), missing]) == 0
    finally:
        for handler in logger.handlers[:]:
            if handler not in old_handlers:
                logger.removeHandler(handler)
                handler.close()


def test_cli_install_and_uninstall_dispatch_and_validation(monkeypatch):
    from vplayer import installer

    monkeypatch.setattr(entry, "QApplication", lambda argv: pytest.fail("Qt started for --install/--uninstall"))
    calls = []
    monkeypatch.setattr(installer, "run_install", lambda *, set_default=False: calls.append(("install", set_default)) or 0)
    monkeypatch.setattr(installer, "run_uninstall", lambda: calls.append(("uninstall", None)) or 0)

    assert entry.main(["--install"]) == 0
    assert entry.main(["--install", "--default"]) == 0
    assert entry.main(["--uninstall"]) == 0
    assert calls == [("install", False), ("install", True), ("uninstall", None)]

    for bad_args in (["--install", "--uninstall"], ["--default"], ["--install", "clip.mp4"]):
        with pytest.raises(SystemExit) as exc_info:
            entry.main(bad_args)
        assert exc_info.value.code == 2


def test_linux_per_user_install_and_uninstall(tmp_path, monkeypatch):
    from vplayer import installer

    commands = []
    monkeypatch.setattr(installer.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(installer.subprocess, "run", lambda cmd, **kw: commands.append(cmd))

    assert installer.install_linux(tmp_path, set_default=True) == 0
    opt_bin = tmp_path / ".local" / "opt" / "vplayer" / "vplayer"
    bin_link = tmp_path / ".local" / "bin" / "vplayer"
    desktop = tmp_path / ".local" / "share" / "applications" / "vplayer.desktop"
    png_icon = tmp_path / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "vplayer.png"
    svg_icon = tmp_path / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps" / "vplayer.svg"

    assert opt_bin.is_file()
    assert bin_link.exists() or bin_link.is_symlink()
    assert desktop.is_file()
    assert png_icon.is_file() and svg_icon.is_file()
    desktop_text = desktop.read_text(encoding="utf-8")
    assert "Categories=AudioVideo;Video;Player;" in desktop_text
    for mime in installer.MIME_TYPES:
        assert mime in desktop_text
    assert any(cmd[0] == "update-desktop-database" for cmd in commands)
    assert any(cmd[0] == "gtk-update-icon-cache" for cmd in commands)
    assert any(cmd[:3] == ["xdg-mime", "default", "vplayer.desktop"] for cmd in commands)

    assert installer.uninstall_linux(tmp_path) == 0
    assert not opt_bin.exists()
    assert not bin_link.exists() and not bin_link.is_symlink()
    assert not desktop.exists()
    assert not png_icon.exists() and not svg_icon.exists()

