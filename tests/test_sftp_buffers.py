import subprocess
from pathlib import Path
from uuid import uuid4

import paramiko
import pytest
from PySide6.QtCore import QTimer

from vplayer.mpv_widget import MpvWidget
from vplayer.player import Player

MEDIA = Path(__file__).resolve().parent / "media"
MIB = 1024 * 1024


@pytest.fixture(scope="module")
def large_media():
    clip = MEDIA / f"cache_{uuid4().hex}.mkv"
    try:
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25",
                "-t", "8", "-vf", "noise=alls=32:allf=t+u",
                "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0",
                "-threads", "2", str(clip),
            ],
            check=True,
        )
        assert clip.stat().st_size >= 16 * MIB
        yield clip
    finally:
        clip.unlink(missing_ok=True)


@pytest.mark.sftp
def test_remote_cache_stays_bounded_during_play_seek_step_and_eof(qtbot, sftp_server, large_media):
    player = Player(readahead_mb=16, backbuffer_mb=8)
    player.mpv.ao = "null"
    player.mpv.pause = True
    widget = MpvWidget(player)
    widget.resize(320, 180)
    samples = []
    timer = QTimer()

    def sample():
        state = player.mpv.demuxer_cache_state
        if state is None:
            return
        forward, total = state["fw-bytes"], state["total-bytes"]
        assert forward + 8 * MIB <= player.readahead_mb * MIB
        assert total <= (player.readahead_mb + player.backbuffer_mb) * MIB
        samples.append((forward, total))

    timer.timeout.connect(sample)
    transport = None
    try:
        widget.show()
        qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
        transport = paramiko.Transport((sftp_server.host, sftp_server.port))
        transport.start_client(timeout=10)
        transport.auth_password("password", sftp_server.password)
        with qtbot.waitSignal(player.file_loaded, timeout=30000):
            player.load(f"/media/{large_media.name}", transport=transport)
        assert player.mpv["demuxer-donate-buffer"] is False
        timer.start(100)
        player.mpv.pause = False
        qtbot.waitUntil(lambda: (player.mpv.time_pos or 0) >= 1, timeout=30000)
        player.mpv.seek(4, reference="absolute", precision="exact")
        qtbot.waitUntil(lambda: (player.mpv.time_pos or 0) >= 4, timeout=30000)
        player.mpv.pause = True
        qtbot.waitUntil(lambda: player.mpv.pause, timeout=10000)
        before_step = len(samples)
        player.frame_step(-1)
        qtbot.waitUntil(lambda: len(samples) >= before_step + 3, timeout=5000)
        player.mpv.pause = False
        qtbot.waitUntil(lambda: player.mpv.eof_reached, timeout=30000)
        sample()
        assert len(samples) >= 10
        assert max(total for _, total in samples) > 6 * MIB
        assert samples[-1][1] <= player.backbuffer_mb * MIB
    finally:
        timer.stop()
        widget.dispose()
        player.close()
        if transport is not None:
            transport.close()
