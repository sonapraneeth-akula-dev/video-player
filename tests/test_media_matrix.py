import json
import subprocess
from pathlib import Path

import pytest

from scripts.make_test_media import AUDIO_CONTAINERS, CONTAINER_AUDIO, VIDEO_CONTAINERS

MEDIA = Path(__file__).resolve().parent / "media"


def codecs(path):
    result = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name",
         "-of", "json", str(path)],
        text=True,
    )
    return [stream["codec_name"] for stream in json.loads(result)["streams"]]


@pytest.mark.parametrize(
    "name",
    ("h264_25.mp4", "h264_30000-1001.mp4", "h264_60.mp4", "h264_25_start2.mkv"),
)
def test_frame_indexed_fixture_is_h264(name):
    assert codecs(MEDIA / name) == ["h264"]


@pytest.mark.parametrize(
    ("codec", "ext"),
    [(codec, ext) for codec, containers in VIDEO_CONTAINERS.items() for ext in containers],
)
def test_video_codec_and_audio_match_container(codec, ext):
    assert codecs(MEDIA / f"matrix_{codec}_{ext}.{ext}") == [codec, CONTAINER_AUDIO[ext]]


@pytest.mark.parametrize(
    ("codec", "ext"),
    [(codec, ext) for codec, native in AUDIO_CONTAINERS.items() for ext in ("mkv", native)],
)
def test_audio_codec_in_mkv_and_native_container(codec, ext):
    assert codecs(MEDIA / f"matrix_{codec}_{ext}.{ext}") == [codec]
