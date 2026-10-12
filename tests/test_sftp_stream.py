from pathlib import Path
from types import SimpleNamespace

import conftest
import paramiko
import pytest

from vplayer.sftp import KnownHosts, SftpStream


class FakeRemoteFile:
    def __init__(self, data: bytes):
        self.data = data
        self.requests = []
        self.closes = 0

    def stat(self):
        return SimpleNamespace(st_size=len(self.data))

    def readv(self, chunks, *, max_concurrent_prefetch_requests):
        assert max_concurrent_prefetch_requests == 64
        assert 1 <= len(chunks) <= 128
        assert all(0 < length <= 32 * 1024 for _, length in chunks)
        self.requests.append(chunks)
        return (self.data[offset:offset + length] for offset, length in chunks)

    def close(self):
        self.closes += 1


def test_sftp_fixture_skips_windows_container_docker(tmp_path_factory, monkeypatch):
    monkeypatch.setattr(conftest.shutil, "which", lambda _: "docker")
    monkeypatch.setattr(
        conftest.subprocess, "run",
        lambda *_, **__: SimpleNamespace(returncode=0, stdout="windows\n"),
    )
    with pytest.raises(pytest.skip.Exception, match="Linux-container"):
        next(conftest.sftp_server.__wrapped__(tmp_path_factory))


def test_block_cache_boundary_seek_and_eof():
    data = bytes(range(251)) * (SftpStream.BLOCK_SIZE // 251 + 1)
    remote = FakeRemoteFile(data)
    stream = SftpStream(remote)
    assert stream.size() == len(data)
    assert stream.read(7) == data[:7]
    assert len(remote.requests) == 1
    assert len(remote.requests[0]) == 128
    assert stream.seek(2) == 2
    assert stream.read(9) == data[2:11]
    assert len(remote.requests) == 1
    assert stream.seek(SftpStream.BLOCK_SIZE - 2) == SftpStream.BLOCK_SIZE - 2
    assert stream.read(10) == data[SftpStream.BLOCK_SIZE - 2:SftpStream.BLOCK_SIZE]
    assert len(remote.requests) == 1
    assert stream.read(10) == data[SftpStream.BLOCK_SIZE:SftpStream.BLOCK_SIZE + 10]
    assert len(remote.requests) == 2
    assert remote.requests[1] == [(SftpStream.BLOCK_SIZE, len(data) - SftpStream.BLOCK_SIZE)]
    assert stream.seek(-1, 2) == len(data) - 1
    assert stream.read(100) == data[-1:]
    assert stream.read(1) == b""
    assert stream.seek(0) == 0
    assert stream.read(1) == data[:1]
    assert len(remote.requests) == 3
    stream.close()
    assert remote.closes == 1


def test_empty_and_past_eof_never_read_remote():
    remote = FakeRemoteFile(b"")
    stream = SftpStream(remote)
    assert stream.read(1) == b""
    assert stream.seek(10) == 10
    assert stream.read(1) == b""
    assert remote.requests == []
    stream.close()


def test_seek_modes_invalid_inputs_close_and_cancel():
    remote = FakeRemoteFile(b"abc")
    stream = SftpStream(remote)
    assert stream.read(0) == b""
    assert stream.seek(2) == 2
    assert stream.seek(-1, 1) == 1
    for offset, whence in ((-1, 0), (-4, 2), (0, 3), (0, 1.0), (True, 0)):
        with pytest.raises(ValueError):
            stream.seek(offset, whence)
    for count in (-1, True, "3"):
        with pytest.raises(ValueError):
            stream.read(count)
    assert stream.read(1) == b"b"
    stream.cancel()
    stream.cancel()
    assert remote.closes == 1
    with pytest.raises(OSError, match="cancelled"):
        stream.read(1)
    with pytest.raises(OSError, match="cancelled"):
        stream.seek(0)
    closed = SftpStream(FakeRemoteFile(b"x"))
    closed.close()
    with pytest.raises(ValueError, match="closed"):
        closed.read(1)
    with pytest.raises(ValueError, match="closed"):
        closed.seek(0)


def test_truncated_remote_block_raises_without_advancing():
    remote = FakeRemoteFile(b"abc")
    stream = SftpStream(remote)
    remote.data = b"ab"
    with pytest.raises(EOFError, match="Expected 3 SFTP bytes"):
        stream.read(1)
    assert stream.seek(0, 1) == 0
    remote.data = b"abc"
    assert stream.read(3) == b"abc"


def test_read_failure_does_not_advance_or_cache_partial_data():
    remote = FakeRemoteFile(b"abc")
    stream = SftpStream(remote)
    readv = remote.readv

    def fail_read(*args, **kwargs):
        raise OSError("link disconnected")

    remote.readv = fail_read
    with pytest.raises(OSError, match="link disconnected"):
        stream.read(2)
    assert stream.seek(0, 1) == 0
    remote.readv = readv
    assert stream.read(2) == b"ab"


def test_cancel_during_read_never_returns_cached_data():
    remote = FakeRemoteFile(b"abc")
    stream = SftpStream(remote)
    readv = remote.readv

    def cancel_read(*args, **kwargs):
        parts = list(readv(*args, **kwargs))
        stream.cancel()
        return parts

    remote.readv = cancel_read
    with pytest.raises(OSError, match="cancelled"):
        stream.read(2)
    assert remote.closes == 1


@pytest.mark.parametrize("size", [None, -1, True, "3"])
def test_invalid_remote_size_is_rejected(size):
    remote = FakeRemoteFile(b"abc")
    remote.stat = lambda: SimpleNamespace(st_size=size)
    with pytest.raises(ValueError, match="Remote file size"):
        SftpStream(remote)


@pytest.mark.sftp
def test_stream_reads_remote_media_without_a_local_copy(sftp_server, tmp_path):
    media = Path(__file__).parent / "media" / "h264_25.mp4"
    expected = media.read_bytes()
    known = KnownHosts(tmp_path / "missing_user", tmp_path / "app" / "known_hosts")
    with paramiko.Transport((sftp_server.host, sftp_server.port)) as transport:
        transport.start_client(timeout=10)
        known.remember(sftp_server.host, sftp_server.port, transport.get_remote_server_key())
        assert known.classify(sftp_server.host, sftp_server.port, transport.get_remote_server_key()) == "trusted"
        transport.auth_password("password", sftp_server.password)
        with paramiko.SFTPClient.from_transport(transport) as sftp, sftp.open(
            "/media/h264_25.mp4", "rb",
        ) as remote:
            stream = SftpStream(remote)
            assert stream.size() == len(expected)
            assert stream.read(128) == expected[:128]
            assert stream.seek(0) == 0
            assert stream.read(len(expected)) == expected
            assert stream.read(1) == b""
            stream.close()
