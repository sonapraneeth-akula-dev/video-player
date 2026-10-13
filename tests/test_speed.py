import math
from pathlib import Path
from time import perf_counter

import pytest
from PySide6.QtCore import QEvent, QObject, Qt, QTimer
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
    window._add_player_tab("Video")
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


def test_action_to_painted_acknowledgement_p95(qtbot, tmp_path: Path):
    class PaintObserver(QObject):
        target = ""
        painted_at = None
        sample = 0

        def eventFilter(self, watched, event):
            if (
                event.type() == QEvent.Type.Paint
                and watched.text() == self.target
                and self.painted_at is None
            ):
                # Event filters run before paintEvent; record after it returns.
                QTimer.singleShot(0, lambda sample=self.sample: self.record_paint(sample))
            return False

        def record_paint(self, sample):
            if sample == self.sample and self.painted_at is None:
                self.painted_at = perf_counter()

    window = MainWindow(Settings(tmp_path / "settings.ini"))
    window._add_player_tab("Video")
    qtbot.addWidget(window)
    window.show()
    observer = PaintObserver(window.speed_label)
    window.speed_label.installEventFilter(observer)
    try:
        qtbot.waitUntil(window.speed_label.isVisible)
        QTest.qWait(50)
        elapsed_ms = []
        for index in range(50):
            speed = 2.0 if index % 2 == 0 else 1.0
            observer.sample += 1
            observer.target = f"{speed:g}×"
            observer.painted_at = None
            started_at = perf_counter()
            window.speed_actions[speed].trigger()
            qtbot.waitUntil(lambda: observer.painted_at is not None, timeout=1000)
            elapsed_ms.append((observer.painted_at - started_at) * 1000)
        p95_ms = sorted(elapsed_ms)[math.ceil(len(elapsed_ms) * 0.95) - 1]
        print(f"Action to painted speed acknowledgement p95: {p95_ms:.1f} ms (n=50)")
        assert p95_ms < 100
    finally:
        window.close()


def test_speed_nudges_are_decimal_and_bounded(qtbot):
    player = Player(video_output="null")
    try:
        for _ in range(20):
            player.nudge_speed(0.05)
        assert player.mpv.speed == 2.0
        for _ in range(40):
            player.nudge_speed(-0.05)
        assert player.mpv.speed == 0.05
        for _ in range(200):
            player.nudge_speed(0.05)
        assert player.mpv.speed == 8.0
        with qtbot.waitSignal(player.error):
            player.nudge_speed(float("nan"))
    finally:
        player.close()


def test_speed_adjustment_actions_use_setting(qtbot, tmp_path: Path):
    settings = Settings(tmp_path / "settings.ini")
    settings.store.setValue("playback/speed_step", "0.1")
    window = MainWindow(settings)
    window._add_player_tab("Video")
    qtbot.addWidget(window)
    window.show()
    try:
        actions = {action.objectName(): action for action in window.playback_menu.actions()}
        for name, shortcut in (("speed_up", "]"), ("speed_down", "["), ("speed_reset", "Backspace")):
            assert actions[name].shortcut().toString() == shortcut
        actions["speed_up"].trigger()
        qtbot.waitUntil(lambda: window.player.mpv.speed == 1.1)
        actions["speed_down"].trigger()
        qtbot.waitUntil(lambda: window.player.mpv.speed == 1.0)
        window.player.set_speed(4)
        actions["speed_reset"].trigger()
        qtbot.waitUntil(lambda: window.player.mpv.speed == 1.0)
        window.activateWindow()
        qtbot.waitUntil(window.isActiveWindow)
        window.video.setFocus()
        qtbot.waitUntil(window.video.hasFocus)
        QTest.qWait(200)
        QTest.keyClick(window.video, Qt.Key.Key_BracketRight)
        qtbot.waitUntil(lambda: window.player.mpv.speed == 1.1)
        QTest.keyClick(window.video, Qt.Key.Key_Backspace)
        qtbot.waitUntil(lambda: window.player.mpv.speed == 1.0)
    finally:
        window.close()
