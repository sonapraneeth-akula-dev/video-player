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
