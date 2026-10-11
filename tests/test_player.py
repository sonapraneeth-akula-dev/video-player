from pathlib import Path

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QApplication

from vplayer.player import Player

MEDIA = Path(__file__).resolve().parent / "media" / "h264_25.mp4"


def test_load_and_observe_on_gui_thread(qtbot):
    player = Player(video_output="null")
    threads = []
    player.file_loaded.connect(
        lambda: threads.append(QThread.currentThread()),
        Qt.ConnectionType.DirectConnection,
    )
    try:
        assert player.mpv["cache-on-disk"] is False
        assert player.mpv["hwdec"] == ["auto-safe"]
        with qtbot.waitSignal(player.file_loaded, timeout=10000):
            player.load(MEDIA)
        assert threads == [QApplication.instance().thread()]
        assert player.state()["duration"] > 0
        player.play_pause()
        qtbot.waitUntil(lambda: player.state()["pause"] is True)
        player.play_pause()
        qtbot.waitUntil(lambda: player.state()["pause"] is False)
    finally:
        player.close()


def test_missing_file_emits_error_without_loading(qtbot, tmp_path):
    player = Player(video_output="null")
    try:
        with qtbot.waitSignal(player.error):
            player.load(tmp_path / "missing.mp4")
        assert player.state()["duration"] is None
    finally:
        player.close()


def test_unplayable_file_reports_mpv_error(qtbot, tmp_path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")
    player = Player(video_output="null")
    try:
        with qtbot.waitSignal(player.error, timeout=5000):
            player.load(broken)
    finally:
        player.close()
