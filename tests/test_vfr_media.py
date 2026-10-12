import json
import subprocess
from itertools import pairwise

from scripts.make_test_media import generate_vfr, passthrough_sync


def test_generated_vfr_clip_alternates_frame_durations(tmp_path):
    path = generate_vfr(tmp_path)
    frames = json.loads(subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name:frame=best_effort_timestamp_time",
            "-of", "json", str(path),
        ],
        text=True,
    ))
    assert frames["streams"][0]["codec_name"] == "h264"
    frames = frames["frames"]
    times = [float(frame["best_effort_timestamp_time"]) for frame in frames]
    assert len(times) == 90
    assert times[-1] > 2
    for index, (start, end) in enumerate(pairwise(times)):
        assert abs((end - start) - (1 / 30 if index % 2 == 0 else 1 / 60)) < 0.001

    video = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0",
        "-frames:v", "4", *passthrough_sync(), "-pix_fmt", "bgr0", "-f", "rawvideo", "-",
    ])
    stride = 256 * 4
    frame_bytes = stride * 144
    assert len(video) == 4 * frame_bytes
    assert [
        sum((video[frame * frame_bytes + 8 * stride + (bit * 16 + 8) * 4 + 2] > 128) << bit for bit in range(4))
        for frame in range(4)
    ] == list(range(4))
