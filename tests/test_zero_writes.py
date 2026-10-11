"""Release audit: loop remote playback for 2 h. On Windows, filter Procmon by
vplayer.exe and CreateFile/WriteFile under the user, temp, and cache directories.
On Linux, run inotifywait -m -r -e create,modify "$HOME" "$TMPDIR"
"$XDG_CACHE_HOME". Allow only settings/log rotations; scan other writes for
a 4 KiB media sample.
"""

import os
import subprocess
import sys
import tempfile
import time
from itertools import pairwise
from pathlib import Path

import paramiko
import pytest
from PySide6.QtCore import QStandardPaths

from vplayer.player import Player

MEDIA = Path(__file__).resolve().parent / "media" / "h264_25.mp4"


def _inventory(roots):
    return {
        file: (file.lstat().st_size, file.lstat().st_mtime_ns, file.is_symlink())
        for root in roots for file in root.rglob("*") if file.is_file() or file.is_symlink()
    }


def _contains_sample(file, sample):
    with file.open("rb") as stream:
        previous = b""
        while chunk := stream.read(1024 * 1024):
            if sample in previous + chunk:
                return True
            previous = chunk[-(len(sample) - 1):]
    return False


def test_write_audit_detects_sample_across_read_boundary(tmp_path):
    file = tmp_path / "cache.bin"
    before = _inventory([tmp_path])
    sample = b"x" * 4095 + b"y"
    file.write_bytes(b"a" * (1024 * 1024 - 100) + sample)
    after = _inventory([tmp_path])
    assert file in after and file not in before
    assert _contains_sample(file, sample)
    assert not _contains_sample(file, b"z" * 4096)


@pytest.mark.sftp
def test_sftp_playback_never_writes_media_to_disk(sftp_server, tmp_path):
    roots = [tmp_path / name for name in ("home", "temp", "cache", "local", "roaming")]
    for root in roots:
        root.mkdir()
    environment = os.environ.copy()
    environment.update({
        "VPLAYER_ZERO_WRITES_WORKER": "1",
        "VPLAYER_TEST_SFTP_HOST": sftp_server.host,
        "VPLAYER_TEST_SFTP_PORT": str(sftp_server.port),
        "VPLAYER_TEST_SFTP_PASSWORD": sftp_server.password,
        "USERPROFILE": str(roots[0]),
        "HOME": str(roots[0]),
        "TMP": str(roots[1]),
        "TEMP": str(roots[1]),
        "TMPDIR": str(roots[1]),
        "XDG_CACHE_HOME": str(roots[2]),
        "LOCALAPPDATA": str(roots[3]),
        "APPDATA": str(roots[4]),
    })
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", f"{Path(__file__).resolve()}::test_zero_writes_worker"],
        env=environment, capture_output=True, text=True, timeout=100, check=False,
    )
    assert result.returncode == 0, f"Zero-write worker exited {result.returncode}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(os.environ.get("VPLAYER_ZERO_WRITES_WORKER") != "1", reason="run in isolated child")
def test_zero_writes_worker(qtbot):
    roots = [Path(os.environ[name]) for name in ("HOME", "TMPDIR", "XDG_CACHE_HOME", "LOCALAPPDATA", "APPDATA")]
    for root in roots:
        assert root.is_dir()
    assert Path.home().resolve() == roots[0].resolve()
    assert Path(tempfile.gettempdir()).resolve() == roots[1].resolve()
    for location in (QStandardPaths.StandardLocation.AppConfigLocation, QStandardPaths.StandardLocation.CacheLocation):
        target = Path(QStandardPaths.writableLocation(location)).resolve()
        assert any(target.is_relative_to(root.resolve()) for root in roots)
    player = Player(video_output="null")
    player.mpv.ao = "null"
    player.mpv.loop_file = "inf"
    assert player.mpv["cache-on-disk"] is False
    positions = []
    transport = paramiko.Transport((os.environ["VPLAYER_TEST_SFTP_HOST"], int(os.environ["VPLAYER_TEST_SFTP_PORT"])))
    try:
        transport.start_client(timeout=10)
        transport.auth_password("password", os.environ["VPLAYER_TEST_SFTP_PASSWORD"])
        before = _inventory(roots)
        with qtbot.waitSignal(player.file_loaded, timeout=15000):
            player.load(f"/media/{MEDIA.name}", transport=transport)
        player.mpv.pause = False
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            qtbot.wait(100)
            if player.mpv.time_pos is not None:
                positions.append(player.mpv.time_pos)
        assert max(positions) >= 8
        assert sum(a - b > 3 for a, b in pairwise(positions)) >= 2
        assert player._sftp_streams
    finally:
        player.close()
        transport.close()
    after = _inventory(roots)
    written = {path for path, metadata in after.items() if before.get(path) != metadata}
    sample = MEDIA.read_bytes()[:4096]
    assert not [path for path in written if not path.is_symlink() and _contains_sample(path, sample)]
    assert not written, f"Unexpected writes during SFTP playback: {sorted(str(path) for path in written)}"
