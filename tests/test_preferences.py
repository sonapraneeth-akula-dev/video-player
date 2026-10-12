from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox

from vplayer.settings import Settings
from vplayer.ui.dialogs import PreferencesDialog
from vplayer.ui.main_window import MainWindow


def test_pitch_preference_controls_live_mpv_and_persists(qtbot, tmp_path):
    path = tmp_path / "settings.ini"
    window = MainWindow(Settings(path))
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
