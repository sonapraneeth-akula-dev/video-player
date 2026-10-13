"""NFR-008: measured completion of a local 4K HEVC backward frame step."""

import json
import math
import os
import random
import subprocess
import time
from pathlib import Path

import pytest
from test_frame_accuracy import frame_index

from vplayer.mpv_widget import MpvWidget
from vplayer.player import Player

MEDIA = Path(__file__).resolve().parent / "media" / "hevc_4k_gop250.mp4"
POSITIONS = tuple(random.Random(20261013).sample(range(2, 299), 50))


@pytest.mark.skipif(
    os.environ.get("VPLAYER_4K_PERF") != "1",
    reason="Opt in on a representative Windows or Ubuntu GPU desktop with VPLAYER_4K_PERF=1",
)
def test_4k_hevc_backstep_p95_under_300ms(qtbot, qapp):
    if not MEDIA.is_file():
        raise FileNotFoundError("Generate 4K fixture with scripts/make_test_media.py --backstep")
    metadata = json.loads(subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,avg_frame_rate,nb_read_packets",
            "-of", "json", str(MEDIA),
        ],
        text=True,
    ))["streams"][0]
    assert (metadata["codec_name"], metadata["width"], metadata["height"], metadata["avg_frame_rate"]) == (
        "hevc", 3840, 2160, "25/1",
    )
    assert int(metadata["nb_read_packets"]) == 300
    keyframes = json.loads(subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
            "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(MEDIA),
        ],
        text=True,
    ))["frames"]
    assert [float(frame["best_effort_timestamp_time"]) for frame in keyframes] == [0.0, 10.0]
    player = Player()
    player.mpv.ao = "null"
    player.mpv.pause = True
    widget = MpvWidget(player)
    widget.resize(640, 360)
    widget.show()
    times = []
    try:
        qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
        with qtbot.waitSignal(player.file_loaded, timeout=30000):
            player.load(MEDIA)
        screenshot_times = []
        for _ in range(5):
            started = time.perf_counter()
            frame_index(player)
            screenshot_times.append((time.perf_counter() - started) * 1000)
        for target in POSITIONS:
            player.mpv.seek(target / 25, reference="absolute", precision="exact")
            qtbot.waitUntil(lambda target=target: frame_index(player) == target, timeout=15000)
            started = time.perf_counter()
            player.frame_step(-1)
            qtbot.waitUntil(lambda target=target: frame_index(player) == target - 1, timeout=15000)
            times.append((time.perf_counter() - started) * 1000)
        p95 = sorted(times)[math.ceil(0.95 * len(times)) - 1]
        print(
            f"4K HEVC GOP 250 back-step: n={len(times)}, p95={p95:.1f} ms, max={max(times):.1f} ms, "
            f"screenshot-max={max(screenshot_times):.1f} ms, hwdec-current={player.mpv.hwdec_current}",
        )
        assert len(times) == 50 and p95 < 300
    finally:
        widget.dispose()
        player.close()
        assert player.wait_closed(10)
