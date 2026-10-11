from pathlib import Path

import pytest
from test_frame_accuracy import frame_index

from scripts.make_test_media import generate_vfr
from vplayer.mpv_widget import MpvWidget
from vplayer.player import Player

MEDIA = Path(__file__).parent / "media"


@pytest.fixture(scope="module")
def paused_video(qapp):
    player = Player()
    player.mpv.ao = "null"
    player.mpv.pause = True
    widget = MpvWidget(player)
    widget.resize(256, 144)
    widget.show()
    try:
        yield player, widget
    finally:
        widget.release()
        player.close()
        widget.close()


@pytest.fixture(scope="module")
def vfr_path(tmp_path_factory):
    return generate_vfr(tmp_path_factory.mktemp("vfr-queue"))


def test_vfr_skips_are_exact_in_both_directions(qtbot, paused_video, vfr_path):
    player, widget = paused_video
    player.mpv.pause = False
    qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
    with qtbot.waitSignal(player.vfr_detected, timeout=10000):
        player.load(vfr_path)
    player.mpv.pause = True
    qtbot.waitUntil(lambda: player.mpv.pause is True, timeout=10000)
    first = frame_index(player)
    assert first >= 20
    statuses = []
    player.skip_status.connect(statuses.append)
    try:
        player.skip_frames(-10)
        qtbot.waitUntil(lambda: statuses and statuses[-1] == "Skipped 10/10", timeout=30000)
        assert frame_index(player) == first - 10
        player.skip_frames(10)
        qtbot.waitUntil(lambda: statuses[-1] == "Skipped 10/10" and frame_index(player) == first, timeout=30000)
        assert "Skipping 0/10" in statuses
    finally:
        player.skip_status.disconnect(statuses.append)


def test_vfr_back_skip_stops_at_first_frame(qtbot, paused_video, vfr_path):
    player, widget = paused_video
    player.mpv.pause = True
    with qtbot.waitSignal(player.file_loaded, timeout=10000):
        player.load(vfr_path)
    qtbot.waitUntil(lambda: widget.grabFramebuffer().pixelColor(128, 72).red() > 35, timeout=10000)
    qtbot.waitUntil(lambda: frame_index(player) == 0, timeout=10000)
    for index in range(1, 4):
        player.frame_step()
        qtbot.waitUntil(lambda index=index: frame_index(player) == index, timeout=10000)
    player.variable_frame_rate = True
    statuses = []
    player.skip_status.connect(statuses.append)
    try:
        player.skip_frames(-10)
        qtbot.waitUntil(lambda: statuses and statuses[-1].startswith("Skipped "), timeout=20000)
        assert statuses[-1] == "Skipped 3/10"
        assert frame_index(player) == 0
    finally:
        player.skip_status.disconnect(statuses.append)


def test_unknown_fps_uses_step_queue_and_another_command_cancels(qtbot, paused_video, monkeypatch):
    player, widget = paused_video
    player.mpv.pause = True
    with qtbot.waitSignal(player.file_loaded, timeout=10000):
        player.load(MEDIA / "h264_25.mp4")
    qtbot.waitUntil(lambda: widget.grabFramebuffer().pixelColor(128, 72).red() > 35, timeout=10000)
    qtbot.waitUntil(lambda: frame_index(player) == 0, timeout=10000)
    monkeypatch.setattr(player, "_fps_values", lambda: (None, None))
    statuses = []
    player.skip_status.connect(statuses.append)
    try:
        player.skip_frames(10)
        qtbot.waitUntil(lambda: statuses and statuses[-1] == "Skipped 10/10", timeout=30000)
        assert frame_index(player) == 10
        player.skip_frames(10)
        qtbot.waitUntil(lambda: "Skipping 1/10" in statuses[-12:], timeout=10000)
        player.set_speed(1.1)
        assert statuses[-1].startswith("Skipped ")
        count = len(statuses)
        qtbot.wait(300)
        assert len(statuses) == count
    finally:
        player.skip_status.disconnect(statuses.append)


def test_forward_skip_stops_at_last_frame(qtbot, paused_video):
    player, _widget = paused_video
    player.mpv.pause = True
    with qtbot.waitSignal(player.file_loaded, timeout=10000):
        player.load(MEDIA / "h264_25.mp4")
    player.mpv.seek(296 / 25, reference="absolute", precision="exact")
    qtbot.waitUntil(lambda: frame_index(player) == 296, timeout=10000)
    player.variable_frame_rate = True
    statuses = []
    player.skip_status.connect(statuses.append)
    try:
        player.skip_frames(10)
        qtbot.waitUntil(lambda: statuses and statuses[-1].startswith("Skipped "), timeout=20000)
        assert statuses[-1] == "Skipped 3/10"
        assert frame_index(player) == 299
    finally:
        player.skip_status.disconnect(statuses.append)


def test_unknown_fps_skip_from_playing_pauses_first(qtbot, paused_video, monkeypatch):
    player, _widget = paused_video
    player.mpv.pause = True
    with qtbot.waitSignal(player.file_loaded, timeout=10000):
        player.load(MEDIA / "h264_25.mp4")
    player.mpv.pause = False
    qtbot.waitUntil(lambda: frame_index(player) > 5, timeout=10000)
    monkeypatch.setattr(player, "_fps_values", lambda: (None, None))
    paused_at = []
    statuses = []

    def record_pause(value):
        if value and not paused_at:
            paused_at.append(round((player.mpv.time_pos or 0) * 25))

    player.paused.connect(record_pause)
    player.skip_status.connect(statuses.append)
    try:
        player.skip_frames(3)
        qtbot.waitUntil(lambda: statuses and statuses[-1] == "Skipped 3/3", timeout=10000)
        assert paused_at
        assert player.mpv.pause is True
        assert frame_index(player) == paused_at[0] + 3
    finally:
        player.paused.disconnect(record_pause)
        player.skip_status.disconnect(statuses.append)


def test_stalled_step_times_out_and_cancels_remaining(qtbot, paused_video, monkeypatch):
    player, _widget = paused_video
    player.mpv.pause = True
    with qtbot.waitSignal(player.file_loaded, timeout=10000):
        player.load(MEDIA / "h264_25.mp4")
    qtbot.waitUntil(lambda: frame_index(player) == 0, timeout=10000)
    monkeypatch.setattr(player, "_fps_values", lambda: (None, None))
    statuses = []
    player.skip_status.connect(statuses.append)
    try:
        monkeypatch.setattr(player.mpv, "command", lambda *args: None)
        player.skip_frames(10)
        assert player._skip_timer.interval() == 2000
        player._skip_timeout()
        assert statuses == ["Skipping 0/10", "Skipped 0/10"]
        assert not player._skip_timer.isActive()

        def fail_step(*_args):
            raise SystemError("decoder unavailable")

        monkeypatch.setattr(player.mpv, "command", fail_step)
        with qtbot.waitSignal(player.error) as signal:
            player.skip_frames(10)
        assert "decoder unavailable" in signal.args[0]
        assert statuses[-1] == "Skipped 0/10"
        assert not player._skip_timer.isActive()
    finally:
        player.skip_status.disconnect(statuses.append)
