import math
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from vplayer.player import Player
from vplayer.settings import Settings
from vplayer.ui.main_window import MainWindow


@pytest.mark.parametrize("speed", (0.25, 0.5, 0.67, 1.0, 2.0, 4.0))
def test_speed_presets_set_exact_mpv_rate(qtbot, speed):
    player = Player(video_output="null")
    try:
        player.set_speed(speed)
        assert player.mpv.speed == speed
    finally:
        player.close()


def test_speed_rejects_invalid_values_and_clamps(qtbot):
    player = Player(video_output="null")
    try:
        for invalid in (float("nan"), float("inf"), True, "fast"):
            with qtbot.waitSignal(player.error):
                player.set_speed(invalid)
            assert player.mpv.speed == 1.0
        player.set_speed(-1)
        assert math.isclose(player.mpv.speed, 0.05)
        player.set_speed(50)
        assert player.mpv.speed == 8.0
    finally:
        player.close()


def test_speed_actions_update_status_label(qtbot, tmp_path: Path):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.show()
    try:
        assert window.speed_label.text() == "1×"
        for index, speed in enumerate((0.25, 0.5, 0.67, 1.0, 2.0, 4.0), start=1):
            action = window.speed_actions[speed]
            assert action.shortcut().toString() == f"Alt+{index}"
            assert action in window.playback_menu.actions()
            action.trigger()
            qtbot.waitUntil(lambda speed=speed: window.speed_label.text() == f"{speed:g}×")
            assert window.player.mpv.speed == speed
        window.activateWindow()
        qtbot.waitUntil(window.isActiveWindow)
        window.video.setFocus()
        qtbot.waitUntil(window.video.hasFocus)
        QTest.qWait(200)
        QTest.keyClick(window.video, Qt.Key.Key_3, Qt.KeyboardModifier.AltModifier)
        qtbot.waitUntil(lambda: window.player.mpv.speed == 0.67)
        qtbot.waitUntil(lambda: window.speed_label.text() == "0.67×")
    finally:
        window.close()
