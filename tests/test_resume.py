import subprocess
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox

from vplayer.player import Player
from vplayer.settings import Settings
from vplayer.ui.dialogs import PreferencesDialog
from vplayer.ui.main_window import MainWindow

SHORT_MEDIA = Path(__file__).parent / "media" / "h264_25.mp4"


@pytest.fixture(scope="module")
def long_media(tmp_path_factory):
    file = tmp_path_factory.mktemp("resume") / "long.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=s=96x64:r=25:d=125",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-g", "25", "-keyint_min", "25", "-sc_threshold", "0", str(file),
        ],
        check=True,
    )
    return file


def test_resume_at_two_minutes_and_disabled_starts_at_zero(qtbot, tmp_path, long_media):
    path = tmp_path / "settings.ini"
    window = MainWindow(Settings(path))
    qtbot.addWidget(window)
    window.player.mpv.ao = "null"
    window.player.mpv.pause = True
    window.show()
    try:
        next(action for action in window.file_menu.actions() if action.text() == "Preferences...").trigger()
        dialog = window.findChild(PreferencesDialog)
        assert not dialog.resume_enabled.isChecked()
        QTest.mouseClick(dialog.resume_enabled, Qt.MouseButton.LeftButton)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        assert window.settings.resume_enabled
        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            window.open_file(long_media)
        window.player.seek(120)
        qtbot.waitUntil(lambda: window.player.mpv.time_pos is not None and abs(window.player.mpv.time_pos - 120) < 1)
    finally:
        window.close()
    assert abs(Settings(path).resume_position(long_media) - 120) < 1

    reopened = MainWindow(Settings(path))
    qtbot.addWidget(reopened)
    reopened.player.mpv.ao = "null"
    reopened.player.mpv.pause = True
    reopened.show()
    try:
        with qtbot.waitSignal(reopened.player.file_loaded, timeout=10000):
            reopened.open_file(long_media)
        qtbot.waitUntil(lambda: reopened.player.mpv.time_pos is not None and abs(reopened.player.mpv.time_pos - 120) < 1)
        next(action for action in reopened.file_menu.actions() if action.text() == "Preferences...").trigger()
        dialog = reopened.findChild(PreferencesDialog)
        assert dialog.resume_enabled.isChecked()
        QTest.mouseClick(dialog.resume_enabled, Qt.MouseButton.LeftButton)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
    finally:
        reopened.close()

    disabled = MainWindow(Settings(path))
    qtbot.addWidget(disabled)
    disabled.player.mpv.ao = "null"
    disabled.player.mpv.pause = True
    disabled.show()
    try:
        assert disabled.settings.resume_enabled is False
        with qtbot.waitSignal(disabled.player.file_loaded, timeout=10000):
            disabled.open_file(long_media)
        assert (disabled.player.mpv.time_pos or 0) < 1
    finally:
        disabled.close()


def test_resume_start_rejects_invalid_values(qtbot, tmp_path):
    player = Player(video_output="null")
    try:
        for position in (-1, float("nan"), float("inf"), True, "2"):
            with pytest.raises(ValueError, match="Start position"):
                player.load(tmp_path / "missing.mp4", start_position=position)
    finally:
        player.close()


def test_opening_another_local_file_saves_the_previous_position(qtbot, tmp_path, long_media):
    path = tmp_path / "settings.ini"
    settings = Settings(path)
    settings.set_resume_enabled(True)
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.player.mpv.ao = "null"
    window.player.mpv.pause = True
    window.show()
    try:
        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            window.open_file(long_media)
        window.player.seek(120)
        qtbot.waitUntil(lambda: window.player.mpv.time_pos is not None and abs(window.player.mpv.time_pos - 120) < 1)
        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            window.open_file(SHORT_MEDIA)
        assert abs(Settings(path).resume_position(long_media) - 120) < 1
        assert Settings(path).resume_position(SHORT_MEDIA) is None
    finally:
        window.close()
    assert Settings(path).resume_position(SHORT_MEDIA) is not None
