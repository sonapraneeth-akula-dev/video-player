"""Ownership of independent player windows."""

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt


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

    def move_tab(self, source, target, tab):
        if source is target or source not in self.windows or target not in self.windows:
            raise ValueError("Tab move requires two registered windows")
        if not QCoreApplication.testAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts):
            raise RuntimeError("Cross-window playback requires shared OpenGL contexts")
        if source._closing or target._closing or source.tabs.indexOf(tab) < 0:
            return False
        if target.tabs.count() >= 4:
            return False
        source._store_active_tab_state()
        if tab.retry_cancel is not None:
            tab.retry_cancel.set()
            tab.retry_cancel = None
        if source._active_tab is tab:
            source._active_tab = None
        source.tabs.take_tab(source.tabs.indexOf(tab))
        tab.owner = target
        target.tabs.new_tab(tab, tab.title)
        target._update_tab_status(tab)
        source.limit_message.hide()
        source.limit_button.hide()
        source._overflow_path = None
        if source.tabs.count() == 0 and len(self.windows) > 1:
            source.close()
        return True

    def window_closed(self, window):
        self.windows.remove(window)
        if self.last_used_window is window:
            self.last_used_window = self.windows[-1] if self.windows else None
        if not self.windows:
            self._event_source.removeEventFilter(self)
            self.app.quit()
