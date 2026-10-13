from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from scripts.make_test_media import generate_vfr
from vplayer.settings import Settings
from vplayer.ui.main_window import MainWindow

MEDIA = Path(__file__).resolve().parent / "media" / "h264_25.mp4"


@pytest.fixture
def clipboard(monkeypatch):
    class Clipboard:
        contents = ""

        def setText(self, text):
            self.contents = text

        def text(self):
            return self.contents

    result = Clipboard()
    monkeypatch.setattr(QApplication, "clipboard", lambda: result)
    return result


@pytest.mark.parametrize(("position", "fps", "expected"), [
    (0, None, "00:00:00.000"),
    (1.2, 25.0, "00:00:01.200 f30"),
    (3723.567, 29.97, "01:02:03.567 f111595"),
])
def test_copy_position_formats_frame_and_updates_clipboard(qtbot, tmp_path, monkeypatch, clipboard, position, fps, expected):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    tab = window._add_player_tab("Video")
    tab.player.mpv.ao = "null"
    qtbot.addWidget(window)
    window.show()
    try:
        assert window.copy_position_action.shortcut().toString() == "Ctrl+Shift+C"
        with qtbot.waitSignal(tab.player.file_loaded, timeout=10000):
            window.open_file(MEDIA)
        tab.player.mpv.pause = True
        monkeypatch.setattr(tab.player, "_fps_values", lambda: (fps, fps))
        monkeypatch.setattr(window, "_position_changed", lambda _position: None)
        window._position = position
        window.copy_position()
        assert clipboard.text() == expected
        assert window.statusBar().currentMessage() == "Position copied to clipboard"
        window.activateWindow()
        qtbot.waitUntil(window.isActiveWindow)
        tab.video.setFocus()
        qtbot.waitUntil(tab.video.hasFocus)
        assert window.copy_position_action.isEnabled()
        clipboard.setText("")
        with qtbot.waitSignal(window.copy_position_action.triggered, timeout=2000):
            QTest.keyClick(tab.video, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        assert clipboard.text() == expected
        window._position = float("nan")
        previous = clipboard.text()
        window.copy_position()
        assert clipboard.text() == previous
        assert "unavailable" in window.banner.text()
    finally:
        window.close()


def test_copy_position_without_a_video_does_not_replace_clipboard(qtbot, tmp_path, clipboard):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.show()
    try:
        clipboard.setText("keep me")
        assert not window.copy_position_action.isEnabled()
        window.copy_position()
        assert clipboard.text() == "keep me"
        assert "Open a video" in window.banner.text()
    finally:
        window.close()


def test_position_formats_milliseconds_frame_number_and_unknown_fps(qtbot, tmp_path, monkeypatch):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    window._add_player_tab("Video")
    qtbot.addWidget(window)
    window.show()
    try:
        assert MainWindow._clock(0) == "00:00:00.000"
        assert MainWindow._clock(3661.9996) == "01:01:02.000"
        assert MainWindow._clock(float("nan")) == "—"
        monkeypatch.setattr(window.player, "_fps_values", lambda: (25.0, 25.0))
        window._duration_changed(3661.25)
        window._position_changed(1.2)
        assert window.time_label.text() == "00:00:01.200 / 01:01:01.250 · f30"
        window.player.variable_frame_rate = True
        window.player.vfr_detected.emit()
        assert window.time_label.text().endswith("≈ f 30")
        monkeypatch.setattr(window.player, "_fps_values", lambda: (None, None))
        window._position_changed(0)
        assert window.time_label.text().endswith("f —")
        action = next(action for action in window.view_menu.actions() if action.objectName() == "toggle_overlay")
        assert action.shortcut().toString() == "I"
        assert window.time_label.isVisible()
        action.trigger()
        assert not window.time_label.isVisible()
        action.trigger()
        assert window.time_label.isVisible()
        window.player.skip_status.emit("Skipping 2/10")
        assert window.statusBar().currentMessage() == "Skipping 2/10"
    finally:
        window.close()


def test_vfr_clip_shows_approximate_frame_label(qtbot, tmp_path):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    window._add_player_tab("Video")
    qtbot.addWidget(window)
    window.player.mpv.ao = "null"
    window.show()
    try:
        with qtbot.waitSignal(window.player.vfr_detected, timeout=10000):
            window.open_file(generate_vfr(tmp_path))
        assert "≈ f " in window.time_label.text()
        assert window._position >= 1
        assert window.time_label.text().startswith(window._clock(window._position))
    finally:
        window.close()
