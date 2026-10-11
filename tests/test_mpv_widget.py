from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QThread
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from vplayer.mpv_widget import MpvWidget
from vplayer.player import Player
from vplayer.settings import Settings
from vplayer.ui.main_window import MainWindow

MEDIA = Path(__file__).resolve().parent / "media" / "h264_25.mp4"


def test_rendered_frame_has_letterbox_and_releases_context(qtbot):
    player = Player()
    widget = MpvWidget(player)
    widget.resize(400, 400)
    widget.show()
    try:
        qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
        with qtbot.waitSignal(player.file_loaded, timeout=10000):
            player.load(MEDIA)
        qtbot.waitUntil(
            lambda: widget.grabFramebuffer().pixelColor(200, 200).red() > 35,
            timeout=10000,
        )
        image = widget.grabFramebuffer()
        assert image.pixelColor(200, 200).red() > 35
        assert image.pixelColor(200, 20) == QColor("black")
    finally:
        widget.dispose()
        player.close()


def test_rendered_widgets_are_destroyed_on_gui_thread_before_player_shutdown(qtbot):
    for _ in range(5):
        player = Player()
        widget = MpvWidget(player)
        widget.resize(256, 144)
        destroyed_on = []
        widget.destroyed.connect(
            lambda _object, destroyed_on=destroyed_on: destroyed_on.append(
                QThread.currentThread() == QApplication.instance().thread(),
            ),
        )
        widget.show()
        try:
            qtbot.waitUntil(lambda widget=widget: widget._render is not None, timeout=10000)
            with qtbot.waitSignal(player.file_loaded, timeout=10000):
                player.load(MEDIA)
            qtbot.waitUntil(
                lambda widget=widget: widget.grabFramebuffer().pixelColor(128, 72).red() > 35,
                timeout=10000,
            )
        finally:
            widget.dispose()
            player.close()
        assert destroyed_on == [True]
        assert not shiboken6.isValid(widget)


def test_closing_window_destroys_render_surface_on_gui_thread(qtbot, tmp_path):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    window.show()
    destroyed_on = []
    window.video.destroyed.connect(lambda: destroyed_on.append(QThread.currentThread() == QApplication.instance().thread()))
    try:
        qtbot.waitUntil(lambda: window.video._render is not None, timeout=10000)
    finally:
        window.close()
    assert destroyed_on == [True]
    assert not shiboken6.isValid(window.video)
    window.close()


def test_dispose_rejects_background_thread(qtbot):
    player = Player()
    widget = MpvWidget(player)
    widget.show()
    try:
        qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
        with ThreadPoolExecutor(max_workers=1) as executor, pytest.raises(RuntimeError, match="GUI thread"):
            executor.submit(widget.dispose).result()
        assert shiboken6.isValid(widget)
    finally:
        widget.dispose()
        player.close()
