import json
import subprocess
from fractions import Fraction

from scripts.make_test_media import FRAMES, SIZE, generate


def test_frame_indexed_clips(tmp_path):
    generate(tmp_path)
    width, height = map(int, SIZE.split("x"))
    for name, rate in (
        ("h264_25.mp4", "25/1"),
        ("h264_30000-1001.mp4", "30000/1001"),
        ("h264_60.mp4", "60/1"),
        ("h264_25_start2.mkv", "25/1"),
    ):
        path = tmp_path / name
        info = json.loads(
            subprocess.check_output([
                "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,avg_frame_rate,nb_read_frames,start_time",
                "-of", "json", str(path),
            ], text=True)
        )["streams"][0]
        assert info["codec_name"] == "h264"
        assert info["avg_frame_rate"] == rate
        assert int(info["nb_read_frames"]) == FRAMES
        if "start2" in name:
            assert float(info["start_time"]) >= 2
        keyframes = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-skip_frame", "nokey", "-show_entries", "frame=best_effort_timestamp_time",
            "-of", "json", str(path),
        ], text=True))["frames"]
        assert len(keyframes) == 2
        assert abs(
            float(keyframes[1]["best_effort_timestamp_time"])
            - float(keyframes[0]["best_effort_timestamp_time"])
            - float(250 / Fraction(rate))
        ) < 0.001

        frames = subprocess.check_output([
            "ffmpeg", "-v", "error", "-i", str(path),
            "-f", "rawvideo", "-pix_fmt", "gray", "-",
        ])
        assert len(frames) == FRAMES * width * height
        for number in (0, 1, 10, 127, 249, 250, FRAMES - 1):
            start = number * width * height
            bits = sum(
                (frames[start + 8 * width + bit * 16 + 8] > 128) << bit
                for bit in range(9)
            )
            assert bits == number, (name, number, bits)
