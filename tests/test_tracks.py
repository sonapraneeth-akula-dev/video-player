from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from vplayer.settings import Settings
from vplayer.ui.main_window import MainWindow

MEDIA = Path(__file__).resolve().parent / "media"


def test_audio_subtitle_menus_select_tracks_and_cycle_with_shortcuts(qtbot, tmp_path):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    window._add_player_tab("Video")
    qtbot.addWidget(window)
    window.show()
    try:
        window.player.mpv.ao = "null"
        assert not window.cycle_audio.isEnabled()
        assert not window.cycle_sub.isEnabled()
        qtbot.waitUntil(lambda: window.video._render is not None, timeout=10000)
        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            window.open_file(MEDIA / "tracks_multi.mkv")

        audio = {action.text(): action for action in window.audio_menu.actions()}
        subtitles = {action.text(): action for action in window.subtitle_menu.actions()}
        assert window.cycle_audio.shortcut().toString() == "A"
        assert window.cycle_sub.shortcut().toString() == "J"
        assert {"Off", "Track 1 (eng)", "Track 2 (fra)"} <= audio.keys()
        assert {"Off", "Track 1 (eng)", "Track 2 (fra)"} <= subtitles.keys()
        assert audio["Off"].isChecked() == (window.player.mpv.aid is False)
        assert subtitles["Off"].isChecked() == (window.player.mpv.sid is False)
        audio["Track 2 (fra)"].trigger()
        qtbot.waitUntil(lambda: window.player.mpv.aid == 2)
        qtbot.waitUntil(
            lambda: next(action for action in window.audio_menu.actions() if action.text() == "Track 2 (fra)").isChecked(),
        )
        next(action for action in window.subtitle_menu.actions() if action.text() == "Track 2 (fra)").trigger()
        qtbot.waitUntil(lambda: window.player.mpv.sid == 2)

        window.activateWindow()
        qtbot.waitUntil(window.isActiveWindow)
        window.video.setFocus()
        qtbot.waitUntil(window.video.hasFocus)
        QTest.keyClick(window.video, Qt.Key.Key_A)
        qtbot.waitUntil(lambda: window.player.mpv.aid is False)
        QTest.keyClick(window.video, Qt.Key.Key_A)
        qtbot.waitUntil(lambda: window.player.mpv.aid == 1)
        QTest.keyClick(window.video, Qt.Key.Key_J)
        qtbot.waitUntil(lambda: window.player.mpv.sid is False)
        QTest.keyClick(window.video, Qt.Key.Key_J)
        qtbot.waitUntil(lambda: window.player.mpv.sid == 1)

        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            window.open_file(MEDIA / "h264_25.mp4")
        assert not window.cycle_audio.isEnabled()
        assert not window.cycle_sub.isEnabled()
        assert [a.text() for a in window.audio_menu.actions() if not a.isSeparator()] == [
            "Next audio track", "Off",
        ]
    finally:
        window.close()


def test_track_menus_refresh_current_mpv_selection_on_open(qtbot, tmp_path):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    window._add_player_tab("Video")
    qtbot.addWidget(window)
    window.show()
    try:
        window.player.mpv.ao = "null"
        qtbot.waitUntil(lambda: window.video._render is not None, timeout=10000)
        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            window.open_file(MEDIA / "tracks_multi.mkv")
        window.player.mpv.sid = "no"
        window.subtitle_menu.aboutToShow.emit()
        assert next(action for action in window.subtitle_menu.actions() if action.text() == "Off").isChecked()
        window.player.mpv.sid = 2
        window.subtitle_menu.aboutToShow.emit()
        assert next(action for action in window.subtitle_menu.actions() if action.text() == "Track 2 (fra)").isChecked()
    finally:
        window.close()
