from pathlib import Path

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage

from vplayer.player import Player
from vplayer.settings import Settings
from vplayer.ui.main_window import MainWindow

MEDIA = Path(__file__).parent / "media" / "h264_25.mp4"


def test_snapshot_saves_native_video_without_overlay_and_never_overwrites(qtbot, tmp_path, monkeypatch):
    settings = Settings(tmp_path / "settings.ini")
    settings.store.setValue("snapshot/dir", str(tmp_path / "snapshots"))
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.player.mpv.ao = "null"
    window.show()
    try:
        assert not window.snapshot_button.isVisible()
        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            window.open_file(MEDIA)
        qtbot.waitUntil(lambda: window.video.grabFramebuffer().pixelColor(128, 72).red() > 35, timeout=10000)
        window.player.mpv.pause = True
        action = next(action for action in window.file_menu.actions() if action.objectName() == "snapshot")
        assert action.shortcut().toString() == "S"
        action.trigger()
        first = next((tmp_path / "snapshots").glob("*.png"))
        qtbot.waitUntil(lambda: first.stat().st_size > 0, timeout=10000)
        image = QImage(str(first))
        assert (image.width(), image.height()) == (256, 144)
        raw = window.player.mpv.command("screenshot-raw", "video")
        assert image.pixelColor(128, 72).red() == raw["data"][72 * raw["stride"] + 128 * 4 + 2]
        original = first.read_bytes()
        action.trigger()
        second = first.with_name(first.stem + "_2.png")
        qtbot.waitUntil(lambda: second.exists() and second.stat().st_size > 0, timeout=10000)
        assert first.read_bytes() == original
        with pytest.raises(FileExistsError):
            window.player.snapshot(first)
        assert first.read_bytes() == original
        window.player._uri = "vpsftp://token/${filename}.mp4"
        sanitized = window.player.snapshot()
        assert "$" not in sanitized.name
        assert sanitized.exists()
        assert window.snapshot_button.isVisible()
        assert "Saved snapshot:" in window.statusBar().currentMessage()
        calls = []
        monkeypatch.setattr("vplayer.ui.main_window.QDesktopServices.openUrl", lambda url: calls.append(url) or True)
        window.snapshot_button.click()
        assert calls == [QUrl.fromLocalFile(str(first.parent))]
    finally:
        window.close()


def test_snapshot_failure_removes_only_the_empty_reserved_file(qtbot, tmp_path, monkeypatch):
    player = Player(video_output="null", snapshot_dir=tmp_path)
    try:
        with qtbot.waitSignal(player.file_loaded, timeout=10000):
            player.load(MEDIA)
        def fail_screenshot(*_args):
            raise SystemError("encoder unavailable")

        monkeypatch.setattr(type(player.mpv), "command", fail_screenshot)
        with pytest.raises(SystemError, match="encoder unavailable"):
            player.snapshot()
        assert list(tmp_path.iterdir()) == []
    finally:
        player.close()


def test_snapshot_rejects_missing_media_and_unsupported_extension(qtbot, tmp_path):
    player = Player(video_output="null", snapshot_dir=tmp_path)
    try:
        with pytest.raises(ValueError, match="before a file is loaded"):
            player.snapshot()
        with qtbot.waitSignal(player.file_loaded, timeout=10000):
            player.load(MEDIA)
        with pytest.raises(ValueError, match="PNG or JPEG"):
            player.snapshot(tmp_path / "frame.txt")
    finally:
        player.close()


def test_snapshot_as_uses_extension_for_jpeg_and_cancel_writes_nothing(qtbot, tmp_path, monkeypatch):
    settings = Settings(tmp_path / "settings.ini")
    settings.store.setValue("snapshot/dir", str(tmp_path))
    settings.store.setValue("snapshot/jpeg_quality", 73)
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.player.mpv.ao = "null"
    window.show()
    try:
        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            window.open_file(MEDIA)
        qtbot.waitUntil(lambda: window.video.grabFramebuffer().pixelColor(128, 72).red() > 35, timeout=10000)
        window.player.mpv.pause = True
        action = next(action for action in window.file_menu.actions() if action.objectName() == "snapshot_as")
        assert action.shortcut().toString() == "Ctrl+Shift+S"
        jpeg = tmp_path / "frame.jpg"
        monkeypatch.setattr(
            "vplayer.ui.main_window.QFileDialog.getSaveFileName",
            lambda *args: (str(jpeg), "JPEG image (*.jpg *.jpeg)"),
        )
        action.trigger()
        qtbot.waitUntil(lambda: jpeg.exists() and jpeg.stat().st_size > 0, timeout=10000)
        assert jpeg.read_bytes().startswith(b"\xff\xd8")
        assert (QImage(str(jpeg)).width(), QImage(str(jpeg)).height()) == (256, 144)
        assert window.player.mpv["screenshot-jpeg-quality"] == 73
        monkeypatch.setattr(
            "vplayer.ui.main_window.QFileDialog.getSaveFileName",
            lambda *args: (str(tmp_path / "frame2"), "PNG image (*.png)"),
        )
        action.trigger()
        png = tmp_path / "frame2.png"
        qtbot.waitUntil(lambda: png.exists() and png.stat().st_size > 0, timeout=10000)
        assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        files = set(tmp_path.iterdir())
        monkeypatch.setattr("vplayer.ui.main_window.QFileDialog.getSaveFileName", lambda *args: ("", ""))
        action.trigger()
        assert set(tmp_path.iterdir()) == files
    finally:
        window.close()
