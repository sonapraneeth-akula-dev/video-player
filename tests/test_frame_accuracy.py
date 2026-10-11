import json
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from vplayer.mpv_widget import MpvWidget
from vplayer.player import Player

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
    player, _widget = paused_video
    player.mpv.pause = True
    with qtbot.waitSignal(player.file_loaded, timeout=10000):
        player.load(MEDIA / name)
    qtbot.waitUntil(lambda: frame_index(player) == 0, timeout=10000)
    for index in range(1, 11):
        player.frame_step()
        qtbot.waitUntil(lambda index=index: frame_index(player) == index, timeout=10000)
    for index in range(9, -1, -1):
        player.frame_step(-1)
        qtbot.waitUntil(lambda index=index: frame_index(player) == index, timeout=10000)


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
