from pathlib import Path
from unittest.mock import Mock

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vplayer.app import AppController
from vplayer.settings import Settings
from vplayer.ui.main_window import MainWindow

MEDIA = Path(__file__).parent / "media" / "h264_25.mp4"


def test_three_windows_own_players_and_only_last_close_quits(qtbot):
    app = Mock()
    controller = AppController(app)
    first = controller.new_window()
    qtbot.addWidget(first)
    try:
        new_window = next(action for action in first.file_menu.actions() if action.text() == "New window")
        assert new_window.shortcut().toString() == "Ctrl+N"
        new_window.trigger()
        second = controller.windows[-1]
        qtbot.addWidget(second)
        third = controller.new_window()
        qtbot.addWidget(third)
        assert len(controller.windows) == 3
        players = []
        for window in (first, second, third):
            window.open_file(MEDIA)
            players.append(window.player)
        qtbot.waitUntil(
            lambda: all(player.mpv.duration is not None for player in players),
            timeout=10000,
        )
        players[0].set_speed(1.5)
        players[2].set_speed(0.5)

        second.close()
        assert players[1].wait_closed(10)
        assert controller.windows == [first, third]
        assert first.isVisible() and third.isVisible()
        assert not players[0]._closed and not players[2]._closed
        assert players[0].mpv.speed == 1.5 and players[2].mpv.speed == 0.5
        app.quit.assert_not_called()

        first.close()
        assert players[0].wait_closed(10)
        app.quit.assert_not_called()
        third.close()
        assert players[2].wait_closed(10)
        assert controller.windows == []
        app.quit.assert_called_once_with()
    finally:
        for window in controller.windows[:]:
            window.close()


def test_standalone_window_ctrl_n_joins_window_registry(qtbot, tmp_path):
    first = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(first)
    first.show()
    second = first.new_window()
    qtbot.addWidget(second)
    controller = first.controller
    controller.app = Mock()
    try:
        assert controller.windows == [first, second]
        assert second.controller is controller and second.isVisible()
        controller.register(first)
        assert controller.windows == [first, second]
        first.close()
        assert controller.windows == [second]
        second.close()
        controller.app.quit.assert_called_once_with()
    finally:
        for window in controller.windows[:]:
            window.close()


def test_shortcuts_target_focused_windows_active_tab(qtbot):
    controller = AppController(QApplication.instance())
    first = controller.new_window()
    second = controller.new_window()
    qtbot.addWidget(first)
    qtbot.addWidget(second)
    try:
        first.open_file(MEDIA)
        other_tab = first.player
        first._add_player_tab("Another video")
        first.open_file(MEDIA)
        active_tab = first.player
        second.open_file(MEDIA)
        second_player = second.player
        qtbot.waitUntil(
            lambda: all(player.mpv.duration is not None for player in (other_tab, active_tab, second_player)),
            timeout=10000,
        )
        first.activateWindow()
        qtbot.waitUntil(first.isActiveWindow)
        first.video.setFocus()
        qtbot.waitUntil(first.video.hasFocus)
        assert controller.last_used_window is first
        QTest.keyClick(first.video, Qt.Key.Key_5, Qt.KeyboardModifier.AltModifier)
        qtbot.waitUntil(lambda: active_tab.mpv.speed == 2)
        assert other_tab.mpv.speed == 1 and second_player.mpv.speed == 1

        second.activateWindow()
        qtbot.waitUntil(second.isActiveWindow)
        second.video.setFocus()
        qtbot.waitUntil(second.video.hasFocus)
        assert controller.last_used_window is second
        QTest.keyClick(second.video, Qt.Key.Key_3, Qt.KeyboardModifier.AltModifier)
        qtbot.waitUntil(lambda: second_player.mpv.speed == 0.67)
        assert active_tab.mpv.speed == 2 and other_tab.mpv.speed == 1
        second.close()
        assert controller.last_used_window is first
    finally:
        for window in controller.windows[:]:
            window.close()
