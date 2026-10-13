"""Ownership of independent player windows."""

from PySide6.QtCore import QObject


class AppController(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.windows = []

    def new_window(self, *, show=True):
        from vplayer.ui.main_window import MainWindow

        window = MainWindow(controller=self)
        self.windows.append(window)
        if show:
            window.show()
        return window

    def register(self, window):
        if window not in self.windows:
            self.windows.append(window)

    def window_closed(self, window):
        self.windows.remove(window)
        if not self.windows:
            self.app.quit()
