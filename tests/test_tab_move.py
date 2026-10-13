from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QVBoxLayout, QWidget

from vplayer.mpv_widget import MpvWidget
from vplayer.player import Player

MEDIA = Path(__file__).parent / "media" / "tracks_multi.mkv"
VIDEO_ONLY = Path(__file__).parent / "media" / "h264_25.mp4"


def has_video_frame(widget):
    image = widget.grabFramebuffer()
    return max(
        max(image.pixelColor(x, y).getRgb()[:3])
        for x in (image.width() // 4, image.width() // 2, image.width() * 3 // 4)
        for y in (image.height() // 4, image.height() // 2, image.height() * 3 // 4)
    ) > 35


@pytest.mark.skipif(
    QCoreApplication.testAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts),
    reason="Recreation only occurs without shared OpenGL contexts",
)
def test_reparent_render_surface_keeps_core_and_video(qtbot):
    first = QWidget()
    second = QWidget()
    first.setLayout(QVBoxLayout())
    second.setLayout(QVBoxLayout())
    first.resize(256, 144)
    second.resize(256, 144)
    player = Player()
    player.mpv.ao = "null"
    widget = MpvWidget(player, first)
    first.layout().addWidget(widget)
    loaded = QSignalSpy(player.file_loaded)
    first.show()
    second.show()
    try:
        qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
        with qtbot.waitSignal(player.file_loaded, timeout=10000):
            player.load(MEDIA)
        player.mpv.pause = True
        player.mpv.seek(1, reference="absolute", precision="exact")
        qtbot.waitUntil(
            lambda: not player.mpv.seeking and (player.mpv.time_pos or 0) >= 0.9,
            timeout=10000,
        )
        position = player.mpv.time_pos
        player.set_speed(1.5)
        player.mpv.volume = 37
        qtbot.waitUntil(lambda: has_video_frame(widget), timeout=10000)
        video_track = next(
            track["id"] for track in player.mpv.track_list
            if track["type"] == "video" and track["selected"]
        )
        old_context = widget.context()
        widget.release()
        assert widget._render is None
        first.layout().removeWidget(widget)
        second.layout().addWidget(widget)
        widget.show()
        qtbot.waitUntil(
            lambda: widget._render is not None and widget.context() is not old_context,
            timeout=10000,
        )
        player.mpv.vid = "no"
        qtbot.waitUntil(
            lambda: not any(
                track["selected"] for track in player.mpv.track_list if track["type"] == "video"
            ),
            timeout=10000,
        )
        player.mpv.vid = video_track
        qtbot.waitUntil(lambda: any(
            track["selected"] for track in player.mpv.track_list if track["type"] == "video"
        ), timeout=10000)
        player.mpv.seek(position, reference="absolute", precision="exact")
        qtbot.waitUntil(lambda: has_video_frame(widget), timeout=10000)
        qtbot.waitUntil(
            lambda: not player.mpv.seeking and abs((player.mpv.time_pos or 0) - position) < 0.1,
            timeout=5000,
        )
        assert loaded.count() == 1
        assert player.mpv.path == str(MEDIA.resolve())
        assert player.mpv.pause is True
        assert player.mpv.speed == 1.5 and player.mpv.volume == 37
    finally:
        widget.dispose()
        player.close()
        assert player.wait_closed(10)
        first.close()
        second.close()


@pytest.mark.skipif(
    not QCoreApplication.testAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts),
    reason="Shared contexts must be enabled before QApplication construction",
)
def test_shared_context_reparent_keeps_video_only_playing(qtbot):
    first = QWidget()
    second = QWidget()
    first.setLayout(QVBoxLayout())
    second.setLayout(QVBoxLayout())
    first.resize(320, 180)
    second.resize(320, 180)
    player = Player()
    widget = MpvWidget(player, first)
    first.layout().addWidget(widget)
    loaded = QSignalSpy(player.file_loaded)
    first.show()
    second.show()
    try:
        qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
        with qtbot.waitSignal(player.file_loaded, timeout=10000):
            player.load(VIDEO_ONLY)
        player.mpv.pause = True
        player.mpv.seek(2, reference="absolute", precision="exact")
        qtbot.waitUntil(lambda: not player.mpv.seeking and (player.mpv.time_pos or 0) >= 1.9)
        qtbot.waitUntil(lambda: has_video_frame(widget))
        position = player.mpv.time_pos
        context = widget.context()
        render = widget._render
        first.layout().removeWidget(widget)
        second.layout().addWidget(widget)
        widget.show()
        qtbot.waitUntil(lambda: has_video_frame(widget), timeout=10000)
        assert widget.context() is context
        assert widget._render is render
        assert loaded.count() == 1
        assert player.mpv.pause is True
        assert abs((player.mpv.time_pos or 0) - position) < 0.1
    finally:
        widget.dispose()
        player.close()
        assert player.wait_closed(10)
        first.close()
        second.close()
