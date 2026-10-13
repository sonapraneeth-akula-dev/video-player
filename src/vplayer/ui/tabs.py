"""Independent playback tabs and the empty-window placeholder."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget

from vplayer.mpv_widget import MpvWidget
from vplayer.player import Player


class PlayerTab(QWidget):
    def __init__(self, player: Player, parent=None):
        super().__init__(parent)
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


class DetachableTabWidget(QTabWidget):
    open_requested = Signal()
    connect_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("Video tabs")
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
        index = self.addTab(tab, label)
        self.setCurrentIndex(index)
        self._show_placeholder()
        return index

    def close_tab(self, index: int) -> PlayerTab | None:
        tab = self.widget(index)
        if not isinstance(tab, PlayerTab):
            return None
        self.removeTab(index)
        tab.close_player()
        tab.deleteLater()
        self._show_placeholder()
        return tab

    def next_tab(self):
        if self.count():
            self.setCurrentIndex((self.currentIndex() + 1) % self.count())

    def prev_tab(self):
        if self.count():
            self.setCurrentIndex((self.currentIndex() - 1) % self.count())
