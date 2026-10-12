from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from vplayer.settings import Settings
from vplayer.ui.main_window import MainWindow

MEDIA = Path(__file__).resolve().parent / "media" / "h264_25.mp4"


def test_play_pause_and_click_drag_seek(qtbot, tmp_path, monkeypatch):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.show()
    try:
        assert not window.controls.play_action.isEnabled()
        assert not window.seek_bar.isEnabled()
        qtbot.waitUntil(lambda: window.video._render is not None, timeout=10000)
        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            window.open_file(MEDIA)
        qtbot.waitUntil(window.seek_bar.isEnabled)
        assert window.controls.play_action.shortcut().toString() == "Space"
        qtbot.waitUntil(lambda: window.controls.play_action.text() == "Pause")

        window.controls.widgetForAction(window.controls.play_action).click()
        qtbot.waitUntil(lambda: window.player.state()["pause"] is True)
        qtbot.waitUntil(lambda: window.controls.play_action.text() == "Play")
        window.activateWindow()
        qtbot.waitUntil(window.isActiveWindow)
        QTest.keyClick(window, Qt.Key.Key_Space)
        qtbot.waitUntil(lambda: window.player.state()["pause"] is False)

        calls = []
        original_seek = window.player.seek

        def record_seek(seconds):
            calls.append(seconds)
            original_seek(seconds)

        monkeypatch.setattr(window.player, "seek", record_seek)
        slider = window.seek_bar
        midpoint = slider.rect().center()
        QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=midpoint)
        assert len(calls) == 1
        assert abs(calls[0] - window._duration / 2) < 0.1
        qtbot.waitUntil(lambda: abs(window.player.state()["time-pos"] - calls[0]) < 10, timeout=10000)

        QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=midpoint)
        QTest.mouseMove(slider, slider.rect().topRight())
        assert len(calls) == 1
        QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=slider.rect().topRight())
        assert len(calls) == 2
        assert abs(calls[-1] - window._duration) < 0.1
        assert " / " in window.time_label.text()
    finally:
        window.close()


def test_volume_mute_and_fullscreen_shortcuts(qtbot, tmp_path):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.show()
    try:
        qtbot.waitUntil(lambda: window.video._render is not None, timeout=10000)
        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            window.open_file(MEDIA)
        window.player.mpv.volume = 40
        QTest.keyClick(window, Qt.Key.Key_Up)
        qtbot.waitUntil(lambda: window.player.mpv.volume == 45)
        QTest.keyClick(window, Qt.Key.Key_Down)
        qtbot.waitUntil(lambda: window.player.mpv.volume == 40)
        QTest.keyClick(window, Qt.Key.Key_M)
        qtbot.waitUntil(lambda: window.player.mpv.mute is True)
        assert window.player.mpv.volume == 40
        QTest.keyClick(window, Qt.Key.Key_M)
        qtbot.waitUntil(lambda: window.player.mpv.mute is False)
        QTest.keyClick(window, Qt.Key.Key_F)
        qtbot.waitUntil(window.isFullScreen)
        QTest.keyClick(window, Qt.Key.Key_F)
        qtbot.waitUntil(lambda: not window.isFullScreen())
        QTest.keyClick(window, Qt.Key.Key_F)
        qtbot.waitUntil(window.isFullScreen)
        QTest.keyClick(window, Qt.Key.Key_Escape)
        qtbot.waitUntil(lambda: not window.isFullScreen())
        assert window.video.grabFramebuffer().pixelColor(200, 200).red() > 35
    finally:
        window.close()


def test_frame_actions_are_available_after_load(qtbot, tmp_path, monkeypatch):
    settings = Settings(tmp_path / "settings.ini")
    settings.store.setValue("playback/skip_frames", 7)
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.show()
    try:
        assert not window.frame_next.isEnabled()
        assert window.frame_next.shortcut().toString() == "."
        assert window.frame_next in window.playback_menu.actions()
        assert not window.frame_prev.isEnabled()
        assert window.frame_prev.shortcut().toString() == ","
        assert window.frame_prev in window.playback_menu.actions()
        skip_actions = {
            action.objectName(): action for action in window.playback_menu.actions()
            if action.objectName() in ("skip_n_fwd", "skip_n_back")
        }
        assert [skip_actions[key].shortcut().toString() for key in ("skip_n_fwd", "skip_n_back")] == [
            "Ctrl+.", "Ctrl+,",
        ]
        assert not any(action.isEnabled() for action in skip_actions.values())
        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            window.open_file(MEDIA)
        assert window.frame_next.isEnabled()
        assert window.frame_prev.isEnabled()
        assert all(action.isEnabled() for action in skip_actions.values())
        window.frame_next.trigger()
        qtbot.waitUntil(lambda: window.player.mpv.pause is True)
        calls = []
        monkeypatch.setattr(window.player, "skip_frames", calls.append)
        skip_actions["skip_n_fwd"].trigger()
        skip_actions["skip_n_back"].trigger()
        assert calls == [7, -7]
    finally:
        window.close()
