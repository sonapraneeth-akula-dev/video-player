"""Main window for local playback."""

from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QLabel, QMainWindow, QVBoxLayout, QWidget

from vplayer import APP_NAME
from vplayer.mpv_widget import MpvWidget
from vplayer.player import Player


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(960, 600)
        self.player = Player(self)

        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        self.banner = QLabel(content)
        self.banner.setAccessibleName("Playback error")
        self.banner.setWordWrap(True)
        self.banner.hide()
        layout.addWidget(self.banner)
        self.video = MpvWidget(self.player, content)
        layout.addWidget(self.video, 1)
        self.setCentralWidget(content)

        open_action = QAction("&Open...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.choose_file)
        self.file_menu = self.menuBar().addMenu("&File")
        self.file_menu.addAction(open_action)
        self.player.error.connect(self.show_error)
        self.player.file_loaded.connect(self.banner.hide)

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Video")
        if path:
            self.open_file(path)

    def open_file(self, path: str | Path):
        self.banner.hide()
        self.player.load(path)

    def show_error(self, message: str):
        self.banner.setText(message)
        self.banner.show()

    def closeEvent(self, event):
        self.video.release()
        self.player.close()
        super().closeEvent(event)
