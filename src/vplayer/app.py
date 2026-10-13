"""Ownership of independent player windows."""

import json
import logging
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt

log = logging.getLogger("vplayer")


def parse_open_request(payload: bytes) -> dict | None:
    if len(payload) > 65536:
        log.warning("Ignoring oversized IPC request")
        return None
    try:
        request = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        log.warning("Ignoring malformed IPC request")
        return None
    if (
        not isinstance(request, dict)
        or type(request.get("v")) is not int or request["v"] != 1
        or type(request.get("new_window")) is not bool
        or not isinstance(request.get("items"), list)
    ):
        log.warning("Ignoring unsupported IPC request")
        return None
    for item in request["items"]:
        if not isinstance(item, str) or not item:
            log.warning("Ignoring IPC request with invalid item")
            return None
        if item.lower().startswith("sftp://"):
            try:
                remote = urlsplit(item)
                if remote.hostname and remote.path:
                    continue
            except ValueError:
                pass
        elif Path(item).is_absolute():
            continue
        log.warning("Ignoring IPC request with invalid path or URI")
        return None
    return request


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
        app.focusChanged.connect(self._focus_changed)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.WindowActivate and watched in self.windows:
            self.last_used_window = watched
        return False

    def _focus_changed(self, _previous, current):
        window = current.window() if current is not None else None
        if window in self.windows:
            self.last_used_window = window

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

    def receive_open_request(self, payload: bytes) -> bool:
        request = parse_open_request(payload)
        if request is None:
            return False
        if request["new_window"] or not self.windows:
            window = self.new_window()
        else:
            window = self.last_used_window or self.windows[-1]
        failures = 0
        for item in request["items"]:
            if window.tabs.count() >= 4:
                window = self.new_window()
            if not open_in_window(window, item, new_tab=True):
                failures += 1
        if failures:
            window.statusBar().showMessage(f"Could not open {failures} file(s)", 10000)
        window.raise_()
        window.activateWindow()
        return True

    def window_closed(self, window):
        self.windows.remove(window)
        if self.last_used_window is window:
            self.last_used_window = self.windows[-1] if self.windows else None
        if not self.windows:
            self._event_source.removeEventFilter(self)
            self.app.quit()
