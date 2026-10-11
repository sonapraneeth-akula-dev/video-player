import ctypes
from unittest.mock import Mock

import mpv
import paramiko
import pytest
from test_frame_accuracy import frame_index
from test_sftp_stream import FakeRemoteFile

from vplayer.mpv_widget import MpvWidget
from vplayer.player import Player


def test_native_stream_callbacks_copy_seek_cancel_and_close(qtbot, monkeypatch):
    player = Player(video_output="null")
    remote = FakeRemoteFile(b"abc\x00def")
    client = Mock()
    client.open.return_value = remote
    monkeypatch.setattr(paramiko.SFTPClient, "from_transport", lambda transport: client)
    buffer = ctypes.create_string_buffer(4)
    try:
        player._register_sftp()
        player._sftp_sources["vpsftp://fixture/test.mp4"] = (Mock(), "/test.mp4")
        info = mpv.StreamCallbackInfo()
        assert player._sftp_open(None, b"vpsftp://fixture/test.mp4", ctypes.pointer(info)) == 0
        client.open.assert_called_once_with("/test.mp4", "rb")
        cookie = info.cookie
        assert player._sftp_size(cookie) == 7
        assert player._sftp_read(cookie, buffer, 4) == 4
        assert buffer.raw == b"abc\x00"
        assert player._sftp_seek(cookie, 3) == 3
        assert player._sftp_read(cookie, buffer, 4) == 4
        assert buffer.raw == b"\x00def"
        assert player._sftp_read(cookie, buffer, 4) == 0
        with qtbot.waitSignal(player.error):
            assert player._sftp_seek(cookie, -1) == mpv.ErrorCode.GENERIC
        player._sftp_cancel(cookie)
        with qtbot.waitSignal(player.error):
            assert player._sftp_read(cookie, buffer, 1) == -1
        player._sftp_close(cookie)
        assert remote.closes == 1
        client.close.assert_called_once_with()
        assert not player._sftp_streams
    finally:
        player.close()


@pytest.mark.parametrize(("readahead", "backbuffer"), [(15, 256), (65, 256), (64, -1), (64, True)])
def test_invalid_remote_buffer_limits_fail_before_starting_mpv(readahead, backbuffer):
    with pytest.raises(ValueError, match="Invalid SFTP buffer limits"):
        Player(video_output="null", readahead_mb=readahead, backbuffer_mb=backbuffer)


@pytest.mark.sftp
def test_mpv_plays_and_seeks_remote_file_without_copy(qtbot, sftp_server):
    player = Player(readahead_mb=32, backbuffer_mb=16)
    player.mpv.ao = "null"
    widget = MpvWidget(player)
    widget.resize(256, 144)
    widget.show()
    try:
        qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
        with paramiko.Transport((sftp_server.host, sftp_server.port)) as transport:
            transport.start_client(timeout=10)
            transport.auth_password("password", sftp_server.password)
            player.mpv.pause = True
            with qtbot.waitSignal(player.file_loaded, timeout=15000):
                player.load("/media/h264_25.mp4", transport=transport)
            assert player.mpv["demuxer-max-bytes"] == 22 * 1024 * 1024
            assert player.mpv["demuxer-max-back-bytes"] == 15 * 1024 * 1024
            assert player.state()["duration"] > 1
            qtbot.waitUntil(lambda: frame_index(player) == 0, timeout=10000)
            player.seek(1)
            player.mpv.seek(1, reference="absolute", precision="exact")
            qtbot.waitUntil(lambda: frame_index(player) in (24, 25), timeout=10000)
            frame = frame_index(player)
            player.mpv.command("frame-step")
            qtbot.waitUntil(lambda: frame_index(player) == frame + 1, timeout=10000)
            player.mpv.command("frame-back-step")
            qtbot.waitUntil(lambda: frame_index(player) == frame, timeout=10000)
            assert player._sftp_streams
            widget.release()
            player.close()
    finally:
        widget.release()
        player.close()
        widget.close()
    assert not player._sftp_streams


@pytest.mark.sftp
def test_sftp_load_failure_reports_error_and_local_load_restores_buffers(qtbot, sftp_server):
    player = Player(video_output="null")
    try:
        with paramiko.Transport((sftp_server.host, sftp_server.port)) as transport:
            transport.start_client(timeout=10)
            transport.auth_password("password", sftp_server.password)
            with qtbot.waitSignal(player.error, timeout=15000) as signal:
                player.load("/media/missing.mp4", transport=transport)
            assert "Could not open remote file" in signal.args[0]
            with qtbot.waitSignal(player.file_loaded, timeout=10000):
                player.load("tests/media/h264_25.mp4")
            assert player.mpv["demuxer-max-bytes"] == 64 * 1024 * 1024
            assert player.mpv["demuxer-max-back-bytes"] == 32 * 1024 * 1024
    finally:
        player.close()
