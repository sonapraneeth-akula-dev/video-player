import json
import subprocess
from fractions import Fraction

import pytest

from scripts.make_test_media import (
    CORRUPT_SOURCES,
    FRAMES,
    MEDIA,
    SIZE,
    generate,
    generate_corrupt,
    passthrough_sync,
)


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        ("-fps_mode -vsync", ("-fps_mode", "passthrough")),
        ("-vsync", ("-vsync", "0")),
    ],
)
def test_passthrough_sync_uses_supported_ffmpeg_option(monkeypatch, available, expected):
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: available)
    assert passthrough_sync() == expected


def test_passthrough_sync_requires_supported_ffmpeg_option(monkeypatch):
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: "")
    with pytest.raises(RuntimeError, match="passthrough"):
        passthrough_sync()


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


def test_corrupt_corpus_is_seeded_and_covers_three_mutations(tmp_path):
    generate_corrupt(tmp_path)
    files = sorted(tmp_path.iterdir())
    assert len(files) == 50
    first_run = {path.name: path.read_bytes() for path in files}
    for path in files:
        index = int(path.name.split("_")[1])
        source, wrong_ext = CORRUPT_SOURCES[index % len(CORRUPT_SOURCES)]
        original = (MEDIA / source).read_bytes()
        data = path.read_bytes()
        if "truncated" in path.name:
            assert 256 <= len(data) < len(original)
            assert data == original[:len(data)]
        elif "flipped" in path.name:
            assert len(data) == len(original)
            assert data[:256] == original[:256]
            assert data != original
        else:
            assert path.suffix == f".{wrong_ext}"
            assert data == original
    generate_corrupt(tmp_path)
    assert {path.name: path.read_bytes() for path in files} == first_run
    generate_corrupt(tmp_path, seed=1)
    assert any(path.read_bytes() != first_run[path.name] for path in files)
