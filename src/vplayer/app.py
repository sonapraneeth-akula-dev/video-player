"""Ownership of independent player windows."""

from pathlib import Path

from PySide6.QtCore import QEvent, QObject


def open_in_window(window, path: str | Path, *, new_tab: bool = False) -> bool:
    if window._closing:
        raise RuntimeError("Cannot open a file in a closed window")
    remote = isinstance(path, str) and path.lower().startswith("sftp://")
    if new_tab and not remote and not Path(path).is_file():
        window._overflow_path = None
        window.limit_message.hide()
        window.limit_button.hide()
        window.show_error(f"File not found: {path}")
        return False
    if new_tab and window.tabs.count() >= 4:
        window.show_tab_limit(path)
        return False
    window.limit_message.hide()
    window.limit_button.hide()
    window._overflow_path = None
    if new_tab and remote:
        window.open_file(path, new_tab=True)
        return True
    if new_tab:
        window._add_player_tab(Path(path).name)
    window.open_file(path)
    return True


class AppController(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self._event_source = app
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
            self._event_source.removeEventFilter(self)
            self.app.quit()
