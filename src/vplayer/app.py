"""Ownership of independent player windows."""

from PySide6.QtCore import QEvent, QObject


class AppController(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.windows = []
        self.last_used_window = None
        app.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.WindowActivate and watched in self.windows:
            self.last_used_window = watched
        return False

    def new_window(self, *, show=True):
        from vplayer.ui.main_window import MainWindow

        window = MainWindow(controller=self)
        self.windows.append(window)
        if self.last_used_window is None:
            self.last_used_window = window
        if show:
            window.show()
        return window

    def register(self, window):
        if window not in self.windows:
            self.windows.append(window)
        if self.last_used_window is None:
            self.last_used_window = window

    def window_closed(self, window):
        self.windows.remove(window)
        if self.last_used_window is window:
            self.last_used_window = self.windows[-1] if self.windows else None
        if not self.windows:
            self.app.removeEventFilter(self)
            self.app.quit()
