"""Independent playback tabs and the empty-window placeholder."""

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QCursor, QDrag
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMenu,
    QPushButton,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from vplayer.mpv_widget import MpvWidget
from vplayer.player import Player


class PlayerTab(QWidget):
    def __init__(self, player: Player, parent=None, *, owner=None):
        super().__init__(parent)
        self.owner = owner
        self.player = player
        player.setParent(self)
        player.shutdown_finished.connect(player.deleteLater)
        self.current_file = None
        self.active_transport = None
        self.transports = []
        self.pending_recent = None
        self.remote_details = None
        self.failed_position = None
        self.retry_cancel = None
        self.reconnect_attempt = None
        self.cache_paused = False
        self.duration = 0.0
        self.position = 0.0
        self.banner_text = ""
        self.banner_visible = False
        self.retry_visible = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.video = MpvWidget(player, self)
        self.video.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.video.setAccessibleName("Video playback")
        layout.addWidget(self.video, 1)

    def close_player(self):
        self.player.setParent(None)
        self.player.close(transports=tuple(self.transports))
        self.transports.clear()


class DetachableTabBar(QTabBar):
    _mime_type = "application/x-vplayer-tab"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._pressed_tab = None
        self._press_pos = None
        self._dragged_tab = None

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed_tab = self.parentWidget().widget(self.tabAt(event.position().toPoint()))
            self._press_pos = event.position().toPoint()

    def mouseReleaseEvent(self, event):
        self._pressed_tab = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._pressed_tab is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and not self.rect().contains(event.position().toPoint())
            and (event.position().toPoint() - self._press_pos).manhattanLength() >= QApplication.startDragDistance()
        ):
            tab = self._pressed_tab
            self._pressed_tab = None
            self._dragged_tab = tab
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(self._mime_type, b"")
            drag.setMimeData(mime)
            try:
                if (
                    drag.exec(Qt.DropAction.MoveAction) != Qt.DropAction.MoveAction
                    and not QApplication.mouseButtons() & Qt.MouseButton.LeftButton
                    and QApplication.widgetAt(QCursor.pos()) is None
                ):
                    self.parentWidget().detach_requested.emit(tab)
            finally:
                self._dragged_tab = None
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _can_receive(self, event):
        source = event.source()
        return (
            event.mimeData().hasFormat(self._mime_type)
            and isinstance(source, DetachableTabBar)
            and source is not self
            and source._dragged_tab is not None
            and self.count() < 4
        )

    def dragEnterEvent(self, event):
        if self._can_receive(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._can_receive(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if self._can_receive(event):
            source = event.source()
            if self.parentWidget().receive_tab(source.parentWidget().window(), source._dragged_tab):
                event.acceptProposedAction()
                return
        event.ignore()

    def contextMenuEvent(self, event):
        tab = self.parentWidget().widget(self.tabAt(event.pos()))
        if tab is None:
            return
        menu = QMenu(self)
        action = menu.addAction("Move tab to new window")
        action.triggered.connect(lambda: self.parentWidget().detach_requested.emit(tab))
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(event.globalPos())


class DetachableTabWidget(QTabWidget):
    open_requested = Signal()
    connect_requested = Signal()
    detach_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("Video tabs")
        self.setTabBar(DetachableTabBar(self))
        self.tabBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabBar().setAccessibleName("Video tab bar")
        self.placeholder = QWidget(self)
        layout = QVBoxLayout(self.placeholder)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel("Open file / Connect to server", self.placeholder)
        label.setAccessibleName("No videos open")
        layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignCenter)
        open_button = QPushButton("Open file", self.placeholder)
        open_button.setAccessibleName("Open file")
        open_button.clicked.connect(self.open_requested)
        layout.addWidget(open_button)
        connect_button = QPushButton("Connect to server", self.placeholder)
        connect_button.setAccessibleName("Connect to server")
        connect_button.clicked.connect(self.connect_requested)
        layout.addWidget(connect_button)
        self._show_placeholder()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.placeholder.setGeometry(self.rect())

    def _show_placeholder(self):
        self.placeholder.setVisible(self.count() == 0)
        if self.count() == 0:
            self.placeholder.raise_()

    def new_tab(self, tab: PlayerTab, label: str) -> int:
        tab.title = label
        index = self.addTab(tab, label)
        self.setCurrentIndex(index)
        self._show_placeholder()
        return index

    def close_tab(self, index: int) -> PlayerTab | None:
        tab = self.widget(index)
        if not isinstance(tab, PlayerTab):
            return None
        self.take_tab(index)
        tab.close_player()
        tab.deleteLater()
        return tab

    def take_tab(self, index: int) -> PlayerTab:
        tab = self.widget(index)
        self.removeTab(index)
        self._show_placeholder()
        return tab

    def receive_tab(self, source, tab):
        return self.window().receive_tab(source, tab)

    def next_tab(self):
        if self.count():
            self.setCurrentIndex((self.currentIndex() + 1) % self.count())

    def prev_tab(self):
        if self.count():
            self.setCurrentIndex((self.currentIndex() - 1) % self.count())
