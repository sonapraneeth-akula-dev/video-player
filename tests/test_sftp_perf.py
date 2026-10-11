import subprocess
import time
from pathlib import Path
from uuid import uuid4

import paramiko
import pytest
from PySide6.QtGui import QColor

from vplayer.mpv_widget import MpvWidget
from vplayer.player import Player

MEDIA = Path(__file__).resolve().parent / "media"


@pytest.fixture(scope="module")
def perf_media():
    clip = MEDIA / f"netem_{uuid4().hex}.mkv"
    try:
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=25",
                "-t", "12", "-vf", "noise=alls=14:allf=t+u",
                "-c:v", "libx264", "-preset", "veryfast",
                "-b:v", "16M", "-maxrate", "16M", "-bufsize", "32M",
                "-g", "50", "-threads", "2", str(clip),
            ],
            check=True,
        )
        assert clip.stat().st_size >= 8 * 1024 * 1024
        yield clip
    finally:
        clip.unlink(missing_ok=True)


@pytest.fixture
def netem_server(sftp_server):
    def netem(*arguments):
        subprocess.run(
            ["docker", "exec", "--privileged", sftp_server.container, "tc", "qdisc", *arguments],
            check=True, capture_output=True, text=True,
        )

    netem("add", "dev", "eth0", "root", "netem", "delay", "50ms", "rate", "50mbit")
    try:
        yield sftp_server
    finally:
        netem("del", "dev", "eth0", "root")


@pytest.mark.sftp
def test_remote_first_frame_and_seek_with_50ms_50mbit_netem(qtbot, netem_server, perf_media):
    player = None
    widget = None
    transport = None
    errors = []
    try:
        player = Player(readahead_mb=16, backbuffer_mb=8)
        player.error.connect(errors.append)
        player.mpv.ao = "null"
        player.mpv.pause = True
        widget = MpvWidget(player)
        widget.resize(320, 180)
        widget.show()
        qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
        transport = paramiko.Transport((netem_server.host, netem_server.port))
        transport.start_client(timeout=10)
        transport.auth_password("password", netem_server.password)
        started = time.perf_counter()
        with qtbot.waitSignal(player.file_loaded, timeout=10000):
            player.load(f"/media/{perf_media.name}", transport=transport)
        qtbot.waitUntil(
            lambda: widget.grabFramebuffer().pixelColor(160, 90) != QColor("black"),
            timeout=10000,
        )
        first_frame = time.perf_counter() - started
        assert first_frame < 3, f"First frame took {first_frame:.3f}s (limit 3s)"

        first_pixel = widget.grabFramebuffer().pixelColor(160, 90)
        player.mpv.pause = False
        started = time.perf_counter()
        player.seek(4)
        qtbot.waitUntil(
            lambda: (player.mpv.time_pos or 0) >= 4
            and not player.mpv.seeking
            and widget.grabFramebuffer().pixelColor(160, 90) != first_pixel,
            timeout=10000,
        )
        seek_time = time.perf_counter() - started
        assert seek_time < 2, f"Seek took {seek_time:.3f}s (limit 2s)"
        assert not errors, f"Remote playback errors: {errors}"
        print(f"netem 50ms / 50mbit: first frame {first_frame:.3f}s, seek {seek_time:.3f}s")
    finally:
        if widget is not None:
            widget.dispose()
        if player is not None:
            player.close()
        if transport is not None:
            transport.close()
