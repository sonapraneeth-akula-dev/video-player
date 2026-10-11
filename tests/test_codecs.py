import os
import subprocess
from pathlib import Path

import pytest

from scripts.make_test_media import AUDIO_CONTAINERS, VIDEO_CONTAINERS
from vplayer.mpv_widget import MpvWidget
from vplayer.player import Player

MEDIA = Path(__file__).resolve().parent / "media"
VIDEO_CASES = [(codec, ext) for codec, containers in VIDEO_CONTAINERS.items() for ext in containers]
AUDIO_CASES = [(codec, ext) for codec, native in AUDIO_CONTAINERS.items() for ext in ("mkv", native)]


@pytest.fixture(scope="module")
def video_session(qapp):
    player = Player()
    player.mpv.ao = "null"
    widget = MpvWidget(player)
    widget.resize(256, 144)
    widget.show()
    errors = []
    player.error.connect(errors.append)
    try:
        yield player, widget, errors
    finally:
        widget.dispose()
        player.close()


@pytest.mark.parametrize(("codec", "ext"), VIDEO_CASES)
def test_video_decodes_renders_and_has_audio(qtbot, video_session, codec, ext):
    player, widget, errors = video_session
    errors.clear()
    qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
    with qtbot.waitSignal(player.file_loaded, timeout=10000):
        player.load(MEDIA / f"matrix_{codec}_{ext}.{ext}")
    player.mpv.pause = False
    qtbot.waitUntil(
        lambda: player.mpv.video_params is not None
        and widget.grabFramebuffer().pixelColor(128, 72).red() > 35,
        timeout=10000,
    )
    assert player.mpv.audio_params is not None
    qtbot.waitUntil(lambda: player.mpv.eof_reached, timeout=10000)
    qtbot.wait(50)
    assert not errors


@pytest.mark.parametrize(("codec", "ext"), AUDIO_CASES)
def test_audio_decodes_without_end_file_error(qtbot, codec, ext):
    player = Player(video_output="null")
    player.mpv.ao = "null"
    errors = []
    player.error.connect(errors.append)
    try:
        with qtbot.waitSignal(player.file_loaded, timeout=10000):
            player.load(MEDIA / f"matrix_{codec}_{ext}.{ext}")
        player.mpv.pause = False
        qtbot.waitUntil(lambda: player.mpv.audio_params is not None, timeout=5000)
        qtbot.waitUntil(lambda: player.mpv.eof_reached, timeout=10000)
        qtbot.wait(50)
        assert not errors
    finally:
        player.close()


@pytest.mark.skipif(not os.environ.get("VPLAYER_BIN"), reason="packaged build not provided")
@pytest.mark.parametrize(("codec", "ext"), VIDEO_CASES + AUDIO_CASES)
def test_packaged_build_decodes_codec(codec, ext):
    binary = Path(os.environ["VPLAYER_BIN"])
    if not binary.is_file():
        pytest.fail(f"VPLAYER_BIN does not exist: {binary}")
    clip = MEDIA / f"matrix_{codec}_{ext}.{ext}"
    kind = "video" if (codec, ext) in VIDEO_CASES else "audio"
    result = subprocess.run(
        [str(binary), "--codec-probe", kind, str(clip)],
        capture_output=True, text=True, timeout=40, check=False,
    )
    assert result.returncode == 0, (
        f"Packaged codec probe exited {result.returncode}: {clip}: {result.stderr}"
    )
