from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from time import perf_counter
from unittest.mock import Mock

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
    window._add_player_tab("Video")
    window.show()
    destroyed_on = []
    video = window.video
    video.destroyed.connect(lambda: destroyed_on.append(QThread.currentThread() == QApplication.instance().thread()))
    try:
        qtbot.waitUntil(lambda: window.video._render is not None, timeout=10000)
    finally:
        window.close()
    assert destroyed_on == [True]
    assert not shiboken6.isValid(video)
    window.close()


def test_release_frees_render_context_without_swapping_update_callback(qtbot, monkeypatch):
    # python-mpv frees the old ctypes thunk before registering a new one; mpv's render thread can call it.
    player = Player()
    widget = MpvWidget(player)
    widget.show()
    try:
        qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
        render = widget._render
        events = []
        original_setattr = type(render).__setattr__
        original_free = type(render).free
        monkeypatch.setattr(
            type(render), "__setattr__",
            lambda self, name, value: events.append(name) or original_setattr(self, name, value),
        )
        monkeypatch.setattr(type(render), "free", lambda self: events.append("free") or original_free(self))
        widget.release()
        assert events[0] == "free"
        assert "update_cb" not in events
    finally:
        widget.dispose()
        player.close()


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


def test_close_playing_video_frees_surface_before_worker_termination(qtbot, monkeypatch):
    player = Player()
    widget = MpvWidget(player)
    widget.resize(256, 144)
    widget.show()
    release_termination = Event()
    terminate_started = Event()
    original_terminate = type(player.mpv).terminate

    def delayed_terminate(mpv):
        if mpv is player.mpv:
            terminate_started.set()
            release_termination.wait(5)
        original_terminate(mpv)

    monkeypatch.setattr(type(player.mpv), "terminate", delayed_terminate)
    try:
        qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
        with qtbot.waitSignal(player.file_loaded, timeout=10000):
            player.load(MEDIA)
        start = perf_counter()
        player.close()
        assert perf_counter() - start < 1
        assert not shiboken6.isValid(widget)
        assert terminate_started.wait(2)
        assert not player._shutdown_done.is_set()
    finally:
        release_termination.set()
        widget.dispose()
        player.close()
        assert player.wait_closed(10)
    assert not player._shutdown_thread.is_alive()


def test_window_close_does_not_wait_for_remote_transport(qtbot, tmp_path):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    window._add_player_tab("Video")
    window.show()
    player = window.player
    video = window.video
    release_transport = Event()
    transport = Mock()
    transport.close.side_effect = lambda: release_transport.wait(5)
    window._transports.append(transport)
    try:
        qtbot.waitUntil(lambda: window.video._render is not None, timeout=10000)
        start = perf_counter()
        window.close()
        assert perf_counter() - start < 1
        assert not shiboken6.isValid(video)
    finally:
        release_transport.set()
        assert player.wait_closed(10)
    transport.close.assert_called_once_with()
    assert not player._shutdown_thread.is_alive()
