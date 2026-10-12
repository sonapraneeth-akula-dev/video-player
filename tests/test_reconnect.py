import ctypes
import subprocess
from threading import Event, Thread
from time import perf_counter
from unittest.mock import Mock

import mpv
import paramiko
import pytest
from PySide6.QtTest import QSignalSpy
from test_sftp_stream import FakeRemoteFile

from vplayer.player import Player
from vplayer.settings import Settings
from vplayer.sftp import KnownHosts, SftpStream, SshPool
from vplayer.ui.main_window import MainWindow


@pytest.fixture
def connected_pool(qtbot, sftp_server, tmp_path):
    with paramiko.Transport((sftp_server.host, sftp_server.port)) as transport:
        transport.start_client(timeout=10)
        key = transport.get_remote_server_key()
    known = KnownHosts(tmp_path / "user_hosts", tmp_path / "app_hosts")
    known.remember(sftp_server.host, sftp_server.port, key)
    pool = SshPool(known)
    with qtbot.waitSignal(pool.connected, timeout=10000) as connection:
        pool.connect(sftp_server.host, sftp_server.port, "password", sftp_server.password)
    transport = connection.args[0]
    yield pool, transport
    transport.close()


@pytest.mark.sftp
def test_reconnect_reauthenticates_and_pins_original_host_key(connected_pool, monkeypatch):
    pool, original = connected_pool
    replacement = pool.reopen_transport(original, Event())
    try:
        assert replacement is not original
        assert replacement.is_authenticated()
        assert replacement.get_remote_server_key() == original.get_remote_server_key()
        with paramiko.SFTPClient.from_transport(replacement) as client:
            assert client.stat("/media/h264_25.mp4").st_size > 0
    finally:
        replacement.close()

    monkeypatch.setattr(
        paramiko.Transport, "get_remote_server_key",
        lambda _transport: paramiko.RSAKey.generate(1024),
    )
    with pytest.raises(paramiko.SSHException, match="host key changed since approval"):
        pool.reopen_transport(original, Event())


@pytest.mark.sftp
def test_reconnect_cancel_interrupts_blocked_authentication(connected_pool, monkeypatch):
    pool, original = connected_pool
    cancel = Event()
    started = Event()
    failures = []

    def blocked(*_args, **_kwargs):
        started.set()
        cancel.wait(10)
        raise OSError("connection aborted")

    monkeypatch.setattr(pool, "_connect", blocked)

    def attempt():
        try:
            pool.reopen_transport(original, cancel)
        except OSError as error:
            failures.append(error)

    worker = Thread(target=attempt)
    worker.start()
    assert started.wait(2)
    start = perf_counter()
    cancel.set()
    worker.join(1)
    assert perf_counter() - start < 1
    assert not worker.is_alive()
    assert len(failures) == 1 and "cancelled" in str(failures[0])
    assert pool.workers.waitForDone(1000)


@pytest.mark.sftp
def test_player_reopens_failed_stream_without_reloading(qtbot, connected_pool, monkeypatch):
    pool, transport = connected_pool
    player = Player(video_output="null")
    uri = "vpsftp://reconnect/h264_25.mp4"
    player._uri = uri
    player._register_sftp()
    player._sftp_sources[uri] = (transport, "/media/h264_25.mp4", pool.reopen_transport)
    info = mpv.StreamCallbackInfo()
    replacements = []
    attempts = []
    player.sftp_transport_changed.connect(lambda *args: replacements.append(args))
    player.sftp_reconnecting.connect(lambda *_args: attempts.append(1))
    replacement = None
    try:
        assert player._sftp_open(None, uri.encode(), ctypes.pointer(info)) == 0
        stream, _client = player._sftp_streams[info.cookie]
        monkeypatch.setattr(stream.remote_file, "readv", lambda *_a, **_k: (_ for _ in ()).throw(OSError("lost")))
        monkeypatch.setattr(stream._cancel_event, "wait", lambda _delay: False)
        assert stream.read(16)
        qtbot.waitUntil(lambda: bool(replacements), timeout=5000)
        replacement = player._sftp_sources[uri][0]
        assert replacement is not transport
        assert replacements == [(uri, transport, replacement)]
        assert attempts == [1]
        assert stream.seek(0, 1) == 16
        assert player._uri == uri
    finally:
        if info.cookie in player._sftp_streams:
            player._sftp_close(info.cookie)
        player.close()
        if replacement is not None:
            replacement.close()


@pytest.mark.sftp
def test_two_streams_share_replacement_transport(qtbot, connected_pool, monkeypatch):
    pool, transport = connected_pool
    player = Player(video_output="null")
    uri = "vpsftp://reconnect/h264_25.mp4"
    player._uri = uri
    player._register_sftp()
    player._sftp_sources[uri] = (transport, "/media/h264_25.mp4", pool.reopen_transport)
    cookies = []
    failures = []
    replacement = None
    workers = []
    try:
        for _ in range(2):
            info = mpv.StreamCallbackInfo()
            assert player._sftp_open(None, uri.encode(), ctypes.pointer(info)) == 0
            cookies.append(info.cookie)
            stream = player._sftp_streams[info.cookie][0]
            monkeypatch.setattr(
                stream.remote_file, "readv",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("lost")),
            )
            monkeypatch.setattr(stream._cancel_event, "wait", lambda _delay: False)

        for cookie in cookies:
            def read(current=cookie):
                try:
                    assert player._sftp_streams[current][0].read(16)
                except Exception as error:  # noqa: BLE001 - report worker failure in test thread
                    failures.append(error)

            worker = Thread(target=read)
            workers.append(worker)
            worker.start()
        qtbot.waitUntil(lambda: all(not worker.is_alive() for worker in workers), timeout=15000)
        assert not failures
        replacement = player._sftp_sources[uri][0]
        assert replacement is not transport
        assert all(
            player._sftp_streams[cookie][1].get_channel().get_transport() is replacement
            for cookie in cookies
        )
    finally:
        for worker in workers:
            worker.join(5)
        for cookie in cookies:
            if cookie in player._sftp_streams:
                player._sftp_close(cookie)
        player.close()
        if replacement is not None:
            replacement.close()


def test_remote_status_follows_reconnect_and_cache_pause(qtbot, tmp_path):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.show()
    uri = "vpsftp://reconnect/test.mp4"
    window.player._uri = uri
    window._active_transport = object()
    try:
        window.player._update.emit("sftp-reconnecting", (uri, 2))
        qtbot.waitUntil(lambda: window.connection_status.isVisible(), timeout=1000)
        assert window.connection_status.text() == "Reconnecting… (attempt 2)"
        window.player._update.emit("paused-for-cache", True)
        window.player._update.emit("sftp-reconnected", uri)
        qtbot.waitUntil(lambda: window.connection_status.text() == "Buffering…", timeout=1000)
        window.player._update.emit("paused-for-cache", False)
        qtbot.waitUntil(lambda: not window.connection_status.isVisible(), timeout=1000)
        window.player._update.emit("sftp-reconnecting", (uri, 3))
        qtbot.waitUntil(lambda: window.connection_status.isVisible(), timeout=1000)
        window.player._update.emit("sftp-retry-failed", uri)
        qtbot.waitUntil(lambda: not window.connection_status.isVisible(), timeout=1000)
    finally:
        window._active_transport = None
        window.close()


def test_exhausted_retry_emits_before_read_error_and_not_on_eof(qtbot, monkeypatch):
    remote = FakeRemoteFile(b"abc")
    stream = SftpStream(remote, reopen=lambda _cancel: FakeRemoteFile(b"abc"), retry_max=0)
    stream.seek(2)
    events = []
    stream.connection_failed.connect(lambda offset: events.append(("failed", offset)))
    monkeypatch.setattr(remote, "readv", lambda *_a, **_k: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(OSError, match="offline"):
        stream.read(1)
    events.append(("returned", stream.seek(0, 1)))
    assert events == [("failed", 2), ("returned", 2)]
    assert stream.failed

    empty = SftpStream(FakeRemoteFile(b""), retry_max=0)
    empty.connection_failed.connect(lambda offset: events.append(("eof-failure", offset)))
    assert empty.read(1) == b""
    assert not empty.failed
    assert events == [("failed", 2), ("returned", 2)]

    player = Player(video_output="null", retry_max=0)
    client = Mock()
    client.open.return_value = remote
    monkeypatch.setattr(paramiko.SFTPClient, "from_transport", lambda _transport: client)
    uri = "vpsftp://failure/test.mp4"
    player._uri = uri
    player._register_sftp()
    player._sftp_sources[uri] = (Mock(), "/test.mp4", None)
    info = mpv.StreamCallbackInfo()
    reported = []
    player.connection_failed.connect(reported.append)
    try:
        assert player._sftp_open(None, uri.encode(), ctypes.pointer(info)) == 0
        player._sftp_streams[info.cookie][0].connection_failed.connect(
            lambda offset: events.append(("native-failed", offset)),
        )
        assert player._sftp_read(info.cookie, ctypes.create_string_buffer(1), 1) == -1
        events.append(("native-returned", -1))
        assert events[-2:] == [("native-failed", 0), ("native-returned", -1)]
        qtbot.waitUntil(lambda: reported == [0.0], timeout=1000)
    finally:
        if info.cookie in player._sftp_streams:
            player._sftp_close(info.cookie)
        player.close()


def test_connection_failure_banner_uses_last_playback_time(qtbot, tmp_path):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.show()
    uri = "vpsftp://reconnect/test.mp4"
    window.player._uri = uri
    window._remote_details = ("sftp://user@host/test.mp4", "/test.mp4", object())
    try:
        window.player._update.emit("time-pos", 14.625)
        window.player._update.emit("sftp-connection-failed", uri)
        qtbot.waitUntil(lambda: window.retry_button.isVisible(), timeout=1000)
        assert window.banner.text() == "Connection lost at 00:00:14.625"
        assert window._failed_position == 14.625
    finally:
        window.close()


def test_retry_failure_keeps_error_and_allows_another_attempt(qtbot, tmp_path):
    class OfflinePool:
        def reopen_transport(self, _previous, _cancel):
            raise OSError("server offline")

    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.show()
    window._remote_details = ("sftp://user@host/test.mp4", "/test.mp4", OfflinePool())
    window._active_transport = object()
    try:
        window._connection_failed(2.5)
        window.retry_button.click()
        qtbot.waitUntil(lambda: "Retry failed" in window.banner.text(), timeout=1000)
        assert "server offline" in window.banner.text()
        assert window.retry_button.isEnabled()
        assert window.retry_button.isVisible()
    finally:
        window._active_transport = None
        window.close()


def test_stale_retry_result_does_not_replace_current_attempt(qtbot, tmp_path):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window._remote_details = ("sftp://user@host/test.mp4", "/test.mp4", object())
    current = Event()
    window._retry_cancel = current
    try:
        window._finish_remote_retry((*window._remote_details, 2.5), OSError("stale"), Event())
        assert window._retry_cancel is current
        assert "stale" not in window.banner.text()
    finally:
        current.set()
        window.close()


@pytest.mark.sftp
def test_docker_pause_resumes_same_media_without_reload(
    qtbot, connected_pool, sftp_server, tmp_path,
):
    pool, transport = connected_pool
    settings = Settings(tmp_path / "settings.ini")
    settings.store.setValue("network/readahead_mb", 16)
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.player.mpv.ao = "null"
    window.player.mpv.pause = True
    window.show()
    loaded = QSignalSpy(window.player.file_loaded)
    paused = False
    info = mpv.StreamCallbackInfo()
    reader = None
    failures = []
    try:
        with qtbot.waitSignal(window.player.file_loaded, timeout=30000):
            window._open_remote(
                f"sftp://password@{sftp_server.host}:{sftp_server.port}/media/h264_25.mp4",
                "/media/h264_25.mp4", transport, pool,
            )
        assert loaded.count() == 1
        assert window.player._sftp_open(
            None, window.player._uri.encode(), ctypes.pointer(info),
        ) == 0
        stream = window.player._sftp_streams[info.cookie][0]

        def read_during_outage():
            try:
                stream.read(16)
            except Exception as error:  # noqa: BLE001 - report worker failure in test thread
                failures.append(error)

        subprocess.run(["docker", "pause", sftp_server.container], check=True, capture_output=True)
        paused = True
        with qtbot.waitSignal(window.player.sftp_reconnecting, timeout=12000):
            reader = Thread(target=read_during_outage)
            reader.start()
        assert window.connection_status.isVisible()
        assert window.connection_status.text().startswith("Reconnecting… (attempt ")
        qtbot.wait(10000)
        subprocess.run(["docker", "unpause", sftp_server.container], check=True, capture_output=True)
        paused = False
        qtbot.waitUntil(lambda: not reader.is_alive(), timeout=25000)
        assert not failures
        assert stream.seek(0, 1) == 16
        qtbot.waitUntil(lambda: window._reconnect_attempt is None, timeout=5000)
        qtbot.waitUntil(lambda: window._active_transport is not transport, timeout=5000)
        assert window._active_transport.is_active()
        assert not transport.is_active()
        window.player.seek(1)
        qtbot.waitUntil(lambda: (window.player.mpv.time_pos or 0) >= 0.8, timeout=10000)
        assert loaded.count() == 1
        assert window.player.mpv.path == window.player._uri
        assert not window.banner.isVisible()
    finally:
        if paused:
            subprocess.run(["docker", "unpause", sftp_server.container], check=True, capture_output=True)
        if reader is not None and reader.is_alive():
            reader.join(5)
        if info.cookie in window.player._sftp_streams:
            window.player._sftp_close(info.cookie)
        window.close()


@pytest.mark.sftp
def test_exhausted_outage_shows_retry_and_resumes_from_banner_position(
    qtbot, connected_pool, sftp_server, tmp_path,
):
    pool, transport = connected_pool
    settings = Settings(tmp_path / "settings.ini")
    settings.store.setValue("network/retry_max", 0)
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.player.mpv.ao = "null"
    window.player.mpv.pause = True
    window.show()
    loaded = QSignalSpy(window.player.file_loaded)
    paused = False
    info = mpv.StreamCallbackInfo()
    reader = None
    try:
        with qtbot.waitSignal(window.player.file_loaded, timeout=20000):
            window._open_remote(
                f"sftp://password@{sftp_server.host}:{sftp_server.port}/media/h264_25.mp4",
                "/media/h264_25.mp4", transport, pool,
            )
        window.player.mpv.pause = False
        qtbot.waitUntil(lambda: window.player._last_position >= 0.8, timeout=10000)
        window.player.mpv.pause = True
        qtbot.wait(100)
        assert window.player._sftp_open(
            None, window.player._uri.encode(), ctypes.pointer(info),
        ) == 0
        result = []
        subprocess.run(["docker", "pause", sftp_server.container], check=True, capture_output=True)
        paused = True
        started = perf_counter()
        reader = Thread(
            target=lambda: result.append(
                window.player._sftp_read(info.cookie, ctypes.create_string_buffer(16), 16),
            ),
        )
        reader.start()
        qtbot.waitUntil(lambda: window.retry_button.isVisible(), timeout=10000)
        assert perf_counter() - started < 240
        assert window.banner.text() == f"Connection lost at {window._clock(window._failed_position)}"
        position = window._failed_position
        assert position >= 0.8
        assert window.retry_button.isEnabled()
        subprocess.run(["docker", "unpause", sftp_server.container], check=True, capture_output=True)
        paused = False
        reader.join(5)
        assert result == [-1]
        window.player._sftp_close(info.cookie)
        with qtbot.waitSignal(window.player.file_loaded, timeout=20000):
            window.retry_button.click()
        assert window.player._start_position == position
        qtbot.waitUntil(lambda: (window.player.mpv.time_pos or 0) >= position - 0.2, timeout=10000)
        assert loaded.count() == 2
        assert not window.retry_button.isVisible()
        assert not window.banner.isVisible()
    finally:
        if paused:
            subprocess.run(["docker", "unpause", sftp_server.container], check=True, capture_output=True)
        if reader is not None and reader.is_alive():
            reader.join(5)
        if info.cookie in window.player._sftp_streams:
            window.player._sftp_close(info.cookie)
        window.close()
