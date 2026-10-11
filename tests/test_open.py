import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import perf_counter

from PySide6.QtWidgets import QApplication, QFileDialog

from vplayer import __main__ as entry
from vplayer.settings import Settings
from vplayer.ui.main_window import MainWindow

MEDIA = Path(__file__).resolve().parent / "media" / "h264_25.mp4"


def test_file_menu_opens_frame_and_errors_are_nonblocking(qtbot, monkeypatch, tmp_path):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.show()
    try:
        qtbot.waitUntil(lambda: window.video._render is not None, timeout=10000)
        missing = tmp_path / "missing.mp4"
        window.open_file(missing)
        assert window.banner.isVisible()
        assert "File not found" in window.banner.text()

        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(MEDIA), ""))
        started = perf_counter()
        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            window.file_menu.actions()[0].trigger()
        qtbot.waitUntil(
            lambda: window.video.grabFramebuffer().pixelColor(200, 200).red() > 35,
            timeout=10000,
        )
        assert perf_counter() - started < 1.5
        assert not window.banner.isVisible()
    finally:
        window.close()


def test_entrypoint_creates_rotating_log(qtbot, monkeypatch, tmp_path):
    app = QApplication.instance()
    logger = logging.getLogger("vplayer")
    old_handlers = logger.handlers[:]
    monkeypatch.setenv("PATH", os.environ["PATH"])
    monkeypatch.setattr(entry, "QApplication", lambda argv: app)
    monkeypatch.setattr(entry.QStandardPaths, "writableLocation", lambda location: str(tmp_path))
    monkeypatch.setattr("vplayer.ui.main_window.Settings", lambda: Settings(tmp_path / "settings.ini"))

    def exit_after_show(self):
        windows = [w for w in self.topLevelWidgets() if isinstance(w, MainWindow) and w.isVisible()]
        assert len(windows) == 1
        windows[0].close()
        return 0

    monkeypatch.setattr(QApplication, "exec", exit_after_show)
    try:
        assert entry.main() == 0
        handler = next(h for h in logger.handlers if isinstance(h, RotatingFileHandler))
        assert Path(handler.baseFilename) == tmp_path / "vplayer.log"
        assert handler.maxBytes == 1_000_000
    finally:
        for handler in logger.handlers:
            if handler not in old_handlers:
                logger.removeHandler(handler)
                handler.close()


def test_seek_actions_use_configured_short_and_long_steps(qtbot, tmp_path, monkeypatch):
    settings = Settings(tmp_path / "settings.ini")
    settings.store.setValue("playback/seek_short_s", 9)
    settings.store.setValue("playback/seek_long_s", 75)
    window = MainWindow(settings)
    qtbot.addWidget(window)
    calls = []
    monkeypatch.setattr(window.player, "seek", lambda seconds, relative: calls.append((seconds, relative)))
    try:
        actions = window.playback_menu.actions()[1:]
        assert [action.shortcut().toString() for action in actions] == [
            "Right", "Left", "Shift+Right", "Shift+Left",
        ]
        for action in actions:
            action.trigger()
        assert calls == [(9, True), (-9, True), (75, True), (-75, True)]
    finally:
        window.close()
