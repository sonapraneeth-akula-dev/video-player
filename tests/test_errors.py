import logging
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton

from vplayer import __main__ as entry
from vplayer.settings import Settings
from vplayer.ui.main_window import MainWindow


def test_uncaught_qt_slot_is_logged_and_shown_without_exiting(qtbot, tmp_path: Path, caplog):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.show()
    button = QPushButton("Raise", window)

    def fail():
        raise ValueError("slot failed")

    button.clicked.connect(fail)
    old_sys, old_thread = sys.excepthook, threading.excepthook
    restore = entry._install_exception_handlers([window])
    try:
        with caplog.at_level(logging.ERROR, logger="vplayer"):
            QTimer.singleShot(0, button.click)
            qtbot.waitUntil(lambda: window.banner.isVisible() and "slot failed" in window.banner.text())
        assert "Unhandled application exception" in caplog.text
        assert window.isVisible()
        window.speed_actions[2.0].trigger()
        qtbot.waitUntil(lambda: window.speed_label.text() == "2×")
    finally:
        restore()
        window.close()
    assert sys.excepthook is old_sys
    assert threading.excepthook is old_thread


def test_worker_exception_is_logged_and_shown_on_gui_thread(qtbot, tmp_path: Path, caplog):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.show()
    restore = entry._install_exception_handlers([window])

    def fail():
        raise RuntimeError("worker failed")

    worker = threading.Thread(target=fail)
    try:
        with caplog.at_level(logging.ERROR, logger="vplayer"):
            worker.start()
            worker.join(timeout=5)
            assert not worker.is_alive()
            qtbot.waitUntil(lambda: window.banner.isVisible() and "worker failed" in window.banner.text())
        assert "Unhandled application exception" in caplog.text
        assert window.isVisible()
    finally:
        restore()
        window.close()


def test_uncaught_error_targets_active_window(qtbot, tmp_path: Path):
    windows = [
        MainWindow(Settings(tmp_path / f"settings-{index}.ini"))
        for index in range(2)
    ]
    for window in windows:
        qtbot.addWidget(window)
        window.show()
    windows[0].activateWindow()
    qtbot.waitUntil(windows[0].isActiveWindow)
    restore = entry._install_exception_handlers(windows)
    try:
        active = QApplication.activeWindow()
        sys.excepthook(ValueError, ValueError("active window failed"), None)
        if active is windows[0]:
            windows[1].activateWindow()
        qtbot.waitUntil(lambda: any("active window failed" in window.banner.text() for window in windows))
        target = active if active in windows else windows[-1]
        assert target.banner.isVisible()
        assert not next(window for window in windows if window is not target).banner.isVisible()
    finally:
        restore()
        for window in windows:
            window.close()


def test_mpv_callback_exception_is_contained_and_reported(qtbot, monkeypatch, tmp_path: Path, caplog):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.show()

    def fail(_event):
        raise RuntimeError("mpv event failed")

    monkeypatch.setattr(window.player, "_handle_event", fail)
    try:
        with caplog.at_level(logging.ERROR, logger="vplayer"):
            window.player._on_event(object())
            qtbot.waitUntil(lambda: window.banner.isVisible() and "mpv event failed" in window.banner.text())
        assert "Unexpected mpv event callback failure" in caplog.text
        assert window.isVisible()
    finally:
        window.close()
