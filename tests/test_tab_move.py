from pathlib import Path
from threading import Event

from PySide6.QtCore import QCoreApplication, QEvent, QMimeData, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QDrag, QMouseEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QMenu, QVBoxLayout, QWidget

from vplayer.app import AppController
from vplayer.mpv_widget import MpvWidget
from vplayer.player import Player

VIDEO_ONLY = Path(__file__).parent / "media" / "h264_25.mp4"


def has_video_frame(widget):
    image = widget.grabFramebuffer()
    return max(
        max(image.pixelColor(x, y).getRgb()[:3])
        for x in (image.width() // 4, image.width() // 2, image.width() * 3 // 4)
        for y in (image.height() // 4, image.height() // 2, image.height() * 3 // 4)
    ) > 35


def test_shared_context_reparent_keeps_video_only_playing(qtbot):
    assert QCoreApplication.testAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    first = QWidget()
    second = QWidget()
    first.setLayout(QVBoxLayout())
    second.setLayout(QVBoxLayout())
    first.resize(320, 180)
    second.resize(320, 180)
    player = Player()
    widget = MpvWidget(player, first)
    first.layout().addWidget(widget)
    loaded = QSignalSpy(player.file_loaded)
    first.show()
    second.show()
    try:
        qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
        with qtbot.waitSignal(player.file_loaded, timeout=10000):
            player.load(VIDEO_ONLY)
        player.mpv.pause = True
        player.mpv.seek(2, reference="absolute", precision="exact")
        qtbot.waitUntil(lambda: not player.mpv.seeking and (player.mpv.time_pos or 0) >= 1.9)
        qtbot.waitUntil(lambda: has_video_frame(widget))
        position = player.mpv.time_pos
        context = widget.context()
        render = widget._render
        first.layout().removeWidget(widget)
        second.layout().addWidget(widget)
        widget.show()
        qtbot.waitUntil(lambda: has_video_frame(widget), timeout=10000)
        assert widget.context() is context
        assert widget._render is render
        assert loaded.count() == 1
        assert player.mpv.pause is True
        assert abs((player.mpv.time_pos or 0) - position) < 0.1
    finally:
        widget.dispose()
        player.close()
        assert player.wait_closed(10)
        first.close()
        second.close()


def test_move_playing_tab_to_another_window_preserves_state_and_signal_routing(qtbot):
    controller = AppController(QApplication.instance())
    source = controller.new_window()
    target = controller.new_window()
    qtbot.addWidget(source)
    qtbot.addWidget(target)
    try:
        source.open_file(VIDEO_ONLY)
        player = source.player
        tab = source.tabs.currentWidget()
        qtbot.waitUntil(lambda: player.mpv.duration is not None, timeout=10000)
        player.mpv.pause = True
        player.mpv.seek(2, reference="absolute", precision="exact")
        qtbot.waitUntil(lambda: not player.mpv.seeking and (player.mpv.time_pos or 0) >= 1.9)
        qtbot.waitUntil(lambda: has_video_frame(tab.video))
        player.set_speed(1.5)
        player.mpv.volume = 37
        position = player.mpv.time_pos
        context = tab.video.context()
        render = tab.video._render
        loaded = QSignalSpy(player.file_loaded)

        assert target.receive_tab(source, tab)
        qtbot.waitUntil(lambda: has_video_frame(target.video), timeout=10000)
        assert source.tabs.count() == 0 and not source.isVisible()
        assert source not in controller.windows
        assert target.tabs.count() == 1 and target.player is player
        assert tab.owner is target
        assert tab.video.context() is context and tab.video._render is render
        assert loaded.count() == 0 and player.mpv.path == str(VIDEO_ONLY.resolve())
        assert player.mpv.pause is True
        assert abs((player.mpv.time_pos or 0) - position) < 0.1
        assert player.mpv.speed == 1.5 and player.mpv.volume == 37
        player.error.emit("Moved-tab error")
        assert target.banner.text() == "Moved-tab error" and target.banner.isVisible()
        assert not source.banner.isVisible()
        player.set_speed(0.75)
        qtbot.waitUntil(lambda: target.speed_label.text() == "0.75×")
        assert source.speed_label.text() == "1×"
    finally:
        for window in controller.windows[:]:
            window.close()


def test_full_target_refuses_drop_without_losing_source_tab(qtbot):
    controller = AppController(QApplication.instance())
    source = controller.new_window()
    target = controller.new_window()
    qtbot.addWidget(source)
    qtbot.addWidget(target)
    try:
        source._add_player_tab("Moving")
        tab = source.tabs.currentWidget()
        for index in range(4):
            target._add_player_tab(f"Tab {index}")
        assert not target.receive_tab(source, tab)
        assert source.tabs.currentWidget() is tab and target.tabs.count() == 4
        source_bar = source.tabs.tabBar()
        source_bar._dragged_tab = tab

        class Drop:
            accepted = False

            def source(self):
                return source_bar

            def mimeData(self):
                mime = QMimeData()
                mime.setData(source_bar._mime_type, b"")
                return mime

            def acceptProposedAction(self):
                self.accepted = True

            def ignore(self):
                self.accepted = False

        drop = Drop()
        target.tabs.tabBar().dragEnterEvent(drop)
        assert not drop.accepted
        target.tabs.tabBar().dropEvent(drop)
        assert not drop.accepted
        assert source.tabs.currentWidget() is tab and target.tabs.count() == 4
        target.close_tab()
        target.tabs.tabBar().dragEnterEvent(drop)
        assert drop.accepted
        target.tabs.tabBar().dropEvent(drop)
        assert drop.accepted
        assert target.player is tab.player and source.tabs.count() == 0
    finally:
        for window in controller.windows[:]:
            window.close()


def test_dragging_tab_out_creates_window_without_reloading(qtbot, monkeypatch):
    controller = AppController(QApplication.instance())
    source = controller.new_window()
    qtbot.addWidget(source)
    try:
        source.open_file(VIDEO_ONLY)
        player = source.player
        qtbot.waitUntil(lambda: player.mpv.duration is not None, timeout=10000)
        tab = source.tabs.currentWidget()
        loaded = QSignalSpy(player.file_loaded)
        bar = source.tabs.tabBar()
        monkeypatch.setattr(QDrag, "exec", lambda *_args: Qt.DropAction.IgnoreAction)
        monkeypatch.setattr(QApplication, "widgetAt", lambda *_args: None)
        press = QPointF(bar.tabRect(0).center())
        bar.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, press, press, Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        ))
        outside = QPointF(-60, press.y())
        bar.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, outside, outside, Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        ))
        assert len(controller.windows) == 1 and source not in controller.windows
        target = controller.windows[-1]
        qtbot.addWidget(target)
        assert target.tabs.currentWidget() is tab and target.player is player
        assert source.tabs.count() == 0 and loaded.count() == 0
    finally:
        for window in controller.windows[:]:
            window.close()


def test_moving_hidden_tab_restores_its_state_without_changing_active_source(qtbot):
    controller = AppController(QApplication.instance())
    source = controller.new_window()
    target = controller.new_window()
    qtbot.addWidget(source)
    qtbot.addWidget(target)
    try:
        hidden = source._add_player_tab("Hidden")
        active = source._add_player_tab("Active")
        original = target._add_player_tab("Original")
        hidden.player.error.emit("Hidden error")
        assert not source.banner.isVisible()
        assert target.receive_tab(source, hidden)
        assert source.tabs.currentWidget() is active and source.player is active.player
        assert target.tabs.currentWidget() is hidden and target.banner.text() == "Hidden error"
        assert target.banner.isVisible()
        hidden.player.error.emit("Target error")
        assert target.banner.text() == "Target error"
        assert not source.banner.isVisible()
        target.tabs.setCurrentWidget(original)
        hidden.player.error.emit("Hidden again")
        assert not target.banner.isVisible()
        target.tabs.setCurrentWidget(hidden)
        assert target.banner.text() == "Hidden again"
    finally:
        for window in controller.windows[:]:
            window.close()


def test_move_cancels_inflight_manual_retry_so_target_can_retry(qtbot):
    controller = AppController(QApplication.instance())
    source = controller.new_window()
    target = controller.new_window()
    qtbot.addWidget(source)
    qtbot.addWidget(target)
    try:
        tab = source._add_player_tab("Retrying")
        cancel = Event()
        source._retry_cancel = cancel
        source._store_active_tab_state()
        assert tab.retry_cancel is cancel
        assert target.receive_tab(source, tab)
        assert cancel.is_set()
        assert tab.retry_cancel is None and target._retry_cancel is None
        assert target.retry_button.isEnabled()
    finally:
        for window in controller.windows[:]:
            window.close()


def test_moving_last_tab_closes_source_but_last_empty_window_stays(qtbot):
    controller = AppController(QApplication.instance())
    source = controller.new_window()
    target = controller.new_window()
    qtbot.addWidget(source)
    qtbot.addWidget(target)
    try:
        first = source._add_player_tab("First")
        last = source._add_player_tab("Last")
        assert target.receive_tab(source, first)
        assert source in controller.windows and source.isVisible()
        assert source.tabs.currentWidget() is last

        assert target.receive_tab(source, last)
        assert source not in controller.windows and not source.isVisible()
        assert target in controller.windows and target.tabs.count() == 2
        assert not first.player._closed and not last.player._closed
        target.close_tab()
        target.close_tab()
        assert target.tabs.count() == 0
        assert target.tabs.placeholder.isVisible() and target.isVisible()
        assert controller.windows == [target]
        assert first.player.wait_closed(10) and last.player.wait_closed(10)
    finally:
        for window in controller.windows[:]:
            window.close()


def test_ctrl_shift_n_moves_active_playback_to_new_window(qtbot):
    controller = AppController(QApplication.instance())
    source = controller.new_window()
    qtbot.addWidget(source)
    try:
        assert not source.move_tab_action.isEnabled()
        source.open_file(VIDEO_ONLY)
        player = source.player
        qtbot.waitUntil(lambda: player.mpv.duration is not None, timeout=10000)
        source._add_player_tab("Other")
        other = source.player
        source.tabs.setCurrentIndex(0)
        tab = source.tabs.currentWidget()
        player.mpv.pause = True
        player.mpv.seek(2, reference="absolute", precision="exact")
        qtbot.waitUntil(lambda: not player.mpv.seeking and (player.mpv.time_pos or 0) >= 1.9)
        player.set_speed(1.25)
        player.mpv.volume = 22
        position = player.mpv.time_pos
        loaded = QSignalSpy(player.file_loaded)

        source.activateWindow()
        qtbot.waitUntil(source.isActiveWindow)
        source.video.setFocus()
        qtbot.waitUntil(source.video.hasFocus)
        qtbot.wait(50)
        QTest.keyClick(
            source.video, Qt.Key.Key_N,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        qtbot.waitUntil(lambda: len(controller.windows) == 2 and controller.windows[-1] is not source)
        target = controller.windows[-1]
        qtbot.addWidget(target)
        assert target.tabs.currentWidget() is tab and target.player is player
        assert source.tabs.count() == 1 and source.player is other
        assert loaded.count() == 0 and not player._closed
        assert player.mpv.pause is True
        assert abs((player.mpv.time_pos or 0) - position) < 0.1
        assert player.mpv.speed == 1.25 and player.mpv.volume == 22
        assert target.move_tab_action.isEnabled()
    finally:
        for window in controller.windows[:]:
            window.close()


def test_tab_context_menu_moves_selected_tab_to_new_window(qtbot, monkeypatch):
    controller = AppController(QApplication.instance())
    source = controller.new_window()
    qtbot.addWidget(source)
    try:
        tab = source._add_player_tab("Video")
        bar = source.tabs.tabBar()
        menus = []
        monkeypatch.setattr(QMenu, "popup", lambda menu, _point: menus.append(menu))
        point = bar.tabRect(0).center()
        bar.contextMenuEvent(QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, point, bar.mapToGlobal(point),
        ))
        assert len(menus) == 1
        action, = menus[0].actions()
        assert action.text() == "Move tab to new window"
        action.trigger()
        assert len(controller.windows) == 1 and controller.windows[0] is not source
        assert controller.windows[0].tabs.currentWidget() is tab
    finally:
        for window in controller.windows[:]:
            window.close()
