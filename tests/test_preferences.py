from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from vplayer.app import AppController
from vplayer.settings import Settings
from vplayer.ui.dialogs import PreferencesDialog
from vplayer.ui.main_window import MainWindow

MEDIA = Path(__file__).resolve().parent / "media" / "matrix_h264_mp4.mp4"


def test_pitch_preference_controls_live_mpv_and_persists(qtbot, tmp_path):
    path = tmp_path / "settings.ini"
    window = MainWindow(Settings(path))
    window._add_player_tab("Video")
    qtbot.addWidget(window)
    window.show()
    try:
        assert window.player.mpv.audio_pitch_correction is True
        action = next(action for action in window.file_menu.actions() if action.text() == "Preferences...")
        action.trigger()
        dialog = window.findChild(PreferencesDialog)
        assert dialog.pitch_correction.isChecked()
        action.trigger()
        assert window.findChildren(PreferencesDialog) == [dialog]
        QTest.mouseClick(dialog.pitch_correction, Qt.MouseButton.LeftButton)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        assert window.player.mpv.audio_pitch_correction is False
        window.player.set_speed(1.5)
        assert window.player.mpv.speed == 1.5
        assert window.player.mpv.audio_pitch_correction is False

        action.trigger()
        dialog = window.findChild(PreferencesDialog)
        assert not dialog.pitch_correction.isChecked()
        QTest.mouseClick(dialog.pitch_correction, Qt.MouseButton.LeftButton)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel).click()
        assert window.player.mpv.audio_pitch_correction is False
        assert Settings(path).store.value("playback/pitch_correction") in (False, "false")
    finally:
        window.close()

    reopened = MainWindow(Settings(path))
    reopened._add_player_tab("Video")
    qtbot.addWidget(reopened)
    try:
        assert reopened.settings.pitch_correction is False
        assert reopened.player.mpv.audio_pitch_correction is False
        action = next(action for action in reopened.file_menu.actions() if action.text() == "Preferences...")
        action.trigger()
        dialog = reopened.findChild(PreferencesDialog)
        QTest.mouseClick(dialog.pitch_correction, Qt.MouseButton.LeftButton)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        assert reopened.player.mpv.audio_pitch_correction is True
        assert Settings(path).store.value("playback/pitch_correction") in (True, "true")
    finally:
        reopened.close()


def test_background_preference_persists_and_updates_all_windows(qtbot, tmp_path, monkeypatch):
    path = tmp_path / "settings.ini"
    monkeypatch.setattr("vplayer.ui.main_window.Settings", lambda: Settings(path))
    controller = AppController(QApplication.instance())
    first = controller.new_window()
    second = controller.new_window()
    qtbot.addWidget(first)
    qtbot.addWidget(second)
    try:
        for window in (first, second):
            window._add_player_tab("First")
            window._add_player_tab("Second")
            assert window.tabs.widget(0).background_mode == "pause"
        first.show_preferences()
        dialog = first.findChild(PreferencesDialog)
        assert dialog.background_tabs.currentData() == "pause"
        assert dialog.background_tabs.accessibleName() == "Background tabs"
        dialog.background_tabs.setCurrentIndex(dialog.background_tabs.findData("muted"))
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel).click()
        assert first.settings.background_tabs == "pause"
        first.show_preferences()
        dialog = first.findChild(PreferencesDialog)
        dialog.background_tabs.setCurrentIndex(dialog.background_tabs.findData("play"))
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        assert first.settings.background_tabs == second.settings.background_tabs == "play"
        assert all(window.tabs.widget(0).background_mode == "play" for window in (first, second))
        restored = Settings(path)
        restored.load()
        assert restored.background_tabs == "play"
        first.show_preferences()
        assert first.findChild(PreferencesDialog).background_tabs.currentData() == "play"
    finally:
        for window in controller.windows[:]:
            window.close()


def test_background_preferences_reject_invalid_mode():
    with pytest.raises(ValueError, match="Invalid background tab mode"):
        PreferencesDialog(True, background_tabs="unexpected")


def test_hardware_decoding_applies_to_existing_and_new_tabs(qtbot, tmp_path, monkeypatch):
    path = tmp_path / "settings.ini"
    monkeypatch.setattr("vplayer.ui.main_window.Settings", lambda: Settings(path))
    controller = AppController(QApplication.instance())
    first = controller.new_window()
    second = controller.new_window()
    qtbot.addWidget(first)
    qtbot.addWidget(second)
    try:
        first._add_player_tab("First")
        second._add_player_tab("Second")
        first.show_preferences()
        dialog = first.findChild(PreferencesDialog)
        assert dialog.hwdec.currentData() == "auto-safe"
        dialog.hwdec.setCurrentIndex(dialog.hwdec.findData("no"))
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel).click()
        assert first.settings.hwdec == "auto-safe"
        first.show_preferences()
        dialog = first.findChild(PreferencesDialog)
        dialog.hwdec.setCurrentIndex(dialog.hwdec.findData("no"))
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        for window in (first, second):
            assert window.settings.hwdec == "no"
            assert window.tabs.widget(0).player.hwdec == "no"
            assert window.tabs.widget(0).player.mpv["hwdec"] in ("no", ["no"])
        first._add_player_tab("Another")
        assert first.player.hwdec == "no"
        with qtbot.waitSignal(first.player.file_loaded, timeout=10000):
            first.player.load(MEDIA)
        assert first.player.mpv["hwdec"] in ("no", ["no"])
        assert first.banner.isHidden()
        assert Settings(path).store.value("playback/hwdec") == "no"
    finally:
        for window in controller.windows[:]:
            window.close()
