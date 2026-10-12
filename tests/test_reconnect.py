import ctypes
import subprocess
from threading import Event, Thread
from time import perf_counter

import mpv
import paramiko
import pytest
from PySide6.QtTest import QSignalSpy

from vplayer.player import Player
from vplayer.settings import Settings
from vplayer.sftp import KnownHosts, SshPool
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
