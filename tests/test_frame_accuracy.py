import json
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from vplayer.mpv_widget import MpvWidget
from vplayer.player import Player
from vplayer.sync import SyncController

MEDIA = Path(__file__).resolve().parent / "media"
CASES = (
    ("h264_25.mp4", "h264", 25, 250, 0),
    ("h264_30000-1001.mp4", "h264", 30000 / 1001, 250, 0),
    ("h264_60.mp4", "h264", 60, 250, 0),
    ("h264_25_start2.mkv", "h264", 25, 250, 2),
    ("matrix_hevc_mp4.mp4", "hevc", 25, None, 0),
    ("matrix_vp9_webm.webm", "vp9", 25, None, 0),
    ("matrix_av1_mp4.mp4", "av1", 25, None, 0),
)


def frame_index(player: Player) -> int:
    image = player.mpv.command("screenshot-raw", "video")
    if image["format"] != "bgr0":
        raise ValueError(f"Unexpected frame format: {image['format']}")
    data, stride = image["data"], image["stride"]
    return sum(
        (data[8 * stride + (bit * 16 + 8) * 4 + 2] > 128) << bit
        for bit in range(min(9, image["w"] // 16))
    )


@pytest.mark.parametrize("offset_frames", (0, 2, -2))
def test_synced_step_skip_and_seek_reach_offset_frames(qtbot, paused_video, offset_frames):
    master, master_widget = paused_video
    follower = Player()
    follower.mpv.ao = "null"
    follower.mpv.pause = True
    follower_widget = MpvWidget(follower)
    follower_widget.resize(256, 144)
    follower_widget.show()
    controller = None
    try:
        qtbot.waitUntil(lambda: master_widget._render is not None and follower_widget._render is not None)
        master.mpv.pause = True
        with qtbot.waitSignal(master.file_loaded, timeout=10000):
            master.load(MEDIA / "h264_25.mp4")
        with qtbot.waitSignal(follower.file_loaded, timeout=10000):
            follower.load(MEDIA / "h264_25.mp4")
        master.mpv.seek(2, reference="absolute", precision="exact")
        follower.mpv.seek(2 - offset_frames / 25, reference="absolute", precision="exact")
        qtbot.waitUntil(lambda: frame_index(master) == 50 and frame_index(follower) == 50 - offset_frames)
        controller = SyncController(master, follower, offset=offset_frames / 25)
        controller.frame_step(-1)
        qtbot.waitUntil(lambda: frame_index(master) == 49 and frame_index(follower) == 49 - offset_frames)
        qtbot.waitUntil(lambda: controller._waiting is None)
        controller.skip_frames(3)
        qtbot.waitUntil(lambda: frame_index(master) == 52 and frame_index(follower) == 52 - offset_frames)
        qtbot.waitUntil(lambda: controller._waiting is None)
        controller.seek(10.0)
        qtbot.waitUntil(lambda: frame_index(master) == 250 and frame_index(follower) == 250 - offset_frames)
        qtbot.waitUntil(lambda: controller._waiting is None)
        controller.set_speed(1.25)
        assert master.mpv.speed == follower.mpv.speed == 1.25
    finally:
        if controller is not None:
            controller.close()
        follower_widget.dispose()
        follower.close()
        assert follower.wait_closed(10)


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
        widget.dispose()
        player.close()


@pytest.mark.parametrize(("name", "codec", "fps", "gop", "start_pts"), CASES)
def test_frame_index_harness_reads_decoded_video(qtbot, paused_video, name, codec, fps, gop, start_pts):
    info = json.loads(subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,avg_frame_rate,start_time",
            "-of", "json", str(MEDIA / name),
        ],
        text=True,
    ))["streams"][0]
    assert info["codec_name"] == codec
    assert abs(float(Fraction(info["avg_frame_rate"])) - fps) < 0.001
    assert abs(float(info["start_time"]) - start_pts) < 0.1
    player, widget = paused_video
    qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
    with qtbot.waitSignal(player.file_loaded, timeout=10000):
        player.load(MEDIA / name)
    qtbot.waitUntil(lambda: widget.grabFramebuffer().pixelColor(128, 72).red() > 35, timeout=10000)
    qtbot.waitUntil(lambda: frame_index(player) == 0, timeout=10000)
    for index in range(1, 11):
        player.mpv.command("frame-step")
        qtbot.waitUntil(lambda index=index: frame_index(player) == index, timeout=10000)
    if gop is not None:
        player.mpv.seek(gop / fps, reference="absolute", precision="exact")
        qtbot.waitUntil(lambda: frame_index(player) in (gop - 1, gop), timeout=10000)
        if frame_index(player) == gop - 1:
            player.mpv.command("frame-step")
            qtbot.waitUntil(lambda: frame_index(player) == gop, timeout=10000)


@pytest.mark.parametrize(("name", "fps"), [(name, fps) for name, _codec, fps, _gop, _start in CASES])
def test_exact_seek_rounding_lands_on_requested_frame(qtbot, paused_video, name, fps):
    player, widget = paused_video
    qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
    player.mpv.pause = True
    with qtbot.waitSignal(player.file_loaded, timeout=10000):
        player.load(MEDIA / name)
    qtbot.waitUntil(lambda: frame_index(player) == 0, timeout=10000)
    for target in (1, 10, 19):
        player.mpv.seek(target / fps, reference="absolute", precision="exact")
        qtbot.waitUntil(lambda target=target: frame_index(player) == target, timeout=5000)
    if name == "h264_25.mp4":
        player.mpv.seek(250 / fps, reference="absolute", precision="exact")
        qtbot.waitUntil(lambda: frame_index(player) == 250, timeout=5000)


@pytest.mark.parametrize("playing", (False, True))
def test_forward_step_is_exact_from_playing_or_paused(qtbot, paused_video, playing):
    player, _widget = paused_video
    player.mpv.pause = True
    with qtbot.waitSignal(player.file_loaded, timeout=10000):
        player.load(MEDIA / "h264_25.mp4")
    qtbot.waitUntil(lambda: frame_index(player) == 0, timeout=10000)
    paused_frames = []
    if playing:
        player.mpv.pause = False
        assert player.mpv.pause is False
        qtbot.waitUntil(lambda: frame_index(player) >= 2, timeout=10000)
        def record_pause(value):
            if value and not paused_frames:
                paused_frames.append(frame_index(player))

        player.paused.connect(record_pause)
    player.frame_step()
    if playing:
        qtbot.waitUntil(lambda: bool(paused_frames), timeout=10000)
        expected = paused_frames[0] + 1
        player.paused.disconnect(record_pause)
    else:
        expected = 1
    qtbot.waitUntil(lambda: player.mpv.pause is True and frame_index(player) == expected, timeout=10000)
    player.frame_step()
    qtbot.waitUntil(lambda: frame_index(player) == expected + 1, timeout=10000)


@pytest.mark.parametrize("name", [case[0] for case in CASES])
def test_back_step_is_exact_across_cfr_matrix(qtbot, paused_video, name):
    player, widget = paused_video
    qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
    player.mpv.pause = True
    with qtbot.waitSignal(player.file_loaded, timeout=10000):
        player.load(MEDIA / name)
    qtbot.waitUntil(lambda: widget.grabFramebuffer().pixelColor(128, 72).red() > 35, timeout=10000)
    qtbot.waitUntil(lambda: frame_index(player) == 0, timeout=10000)
    for index in range(1, 11):
        player.frame_step()
        qtbot.waitUntil(lambda index=index: frame_index(player) == index, timeout=10000)
    for index in range(9, -1, -1):
        player.frame_step(-1)
        qtbot.waitUntil(lambda index=index: frame_index(player) == index, timeout=10000)


@pytest.mark.parametrize("name", [case[0] for case in CASES])
def test_skip_frames_is_exact_and_clamps_to_file_bounds(qtbot, paused_video, name):
    player, widget = paused_video
    qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
    player.mpv.pause = True
    with qtbot.waitSignal(player.file_loaded, timeout=10000):
        player.load(MEDIA / name)
    qtbot.waitUntil(lambda: widget.grabFramebuffer().pixelColor(128, 72).red() > 35, timeout=10000)
    qtbot.waitUntil(lambda: frame_index(player) == 0, timeout=10000)
    player.skip_frames(10)
    qtbot.waitUntil(lambda: frame_index(player) == 10, timeout=10000)
    player.skip_frames(-10)
    qtbot.waitUntil(lambda: frame_index(player) == 0, timeout=10000)
    player.skip_frames(-10)
    qtbot.waitUntil(lambda: frame_index(player) == 0, timeout=10000)
    player.skip_frames(1000)
    last = 24 if name.startswith("matrix_") else 299
    qtbot.waitUntil(lambda: frame_index(player) == last, timeout=10000)
    player.skip_frames(10)
    qtbot.waitUntil(lambda: frame_index(player) == last, timeout=10000)


def test_skip_from_playing_pauses_before_exact_seek(qtbot, paused_video):
    player, _widget = paused_video
    player.mpv.pause = True
    with qtbot.waitSignal(player.file_loaded, timeout=10000):
        player.load(MEDIA / "h264_25.mp4")
    player.mpv.pause = False
    qtbot.waitUntil(lambda: frame_index(player) > 5, timeout=10000)
    paused_frames = []

    def record_pause(value):
        if value and not paused_frames:
            paused_frames.append(round((player.mpv.time_pos or 0) * player.frame_rate()))

    player.paused.connect(record_pause)
    try:
        player.skip_frames(10)
        qtbot.waitUntil(lambda: bool(paused_frames), timeout=10000)
        qtbot.waitUntil(
            lambda: player.mpv.pause is True and frame_index(player) == paused_frames[0] + 10, timeout=10000,
        )
    finally:
        player.paused.disconnect(record_pause)


@pytest.mark.parametrize("count", [0, 1001, -1001, True, 1.0, "10"])
def test_skip_frames_rejects_invalid_count(paused_video, count):
    player, _widget = paused_video
    with pytest.raises(ValueError, match="Frame skip"):
        player.skip_frames(count)


def test_back_step_from_playing_pauses_then_moves_one_frame(qtbot, paused_video):
    player, _widget = paused_video
    player.mpv.pause = True
    with qtbot.waitSignal(player.file_loaded, timeout=10000):
        player.load(MEDIA / "h264_25.mp4")
    player.mpv.pause = False
    qtbot.waitUntil(lambda: frame_index(player) > 5, timeout=10000)
    paused_frames = []

    def record_pause(value):
        if value and not paused_frames:
            paused_frames.append(frame_index(player))

    player.paused.connect(record_pause)
    try:
        player.frame_step(-1)
        qtbot.waitUntil(lambda: bool(paused_frames), timeout=10000)
        expected = paused_frames[0] - 1
        qtbot.waitUntil(lambda: player.mpv.pause is True and frame_index(player) == expected, timeout=10000)
    finally:
        player.paused.disconnect(record_pause)


@pytest.mark.parametrize("direction", [0, 2, -2, True, 1.0, "1"])
def test_frame_step_rejects_invalid_direction(qtbot, paused_video, direction):
    player, _widget = paused_video
    with pytest.raises(ValueError, match="Frame step direction"):
        player.frame_step(direction)
