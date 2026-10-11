import paramiko
import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from vplayer.sftp import KnownHosts, SshPool


@pytest.fixture
def trusted_pool(sftp_server, tmp_path):
    with paramiko.Transport((sftp_server.host, sftp_server.port)) as transport:
        transport.start_client(timeout=10)
        key = transport.get_remote_server_key()
    known = KnownHosts(tmp_path / "missing_user", tmp_path / "app" / "known_hosts")
    known.remember(sftp_server.host, sftp_server.port, key)
    return SshPool(known)


@pytest.mark.sftp
def test_password_connects_off_gui_thread_with_keepalive(qtbot, trusted_pool, sftp_server, monkeypatch):
    threads = []
    original = paramiko.Transport.start_client
    keepalive = paramiko.Transport.set_keepalive
    intervals = []

    def record_worker(transport, *args, **kwargs):
        threads.append(QThread.currentThread())
        return original(transport, *args, **kwargs)

    def record_keepalive(transport, interval):
        intervals.append(interval)
        return keepalive(transport, interval)

    monkeypatch.setattr(paramiko.Transport, "start_client", record_worker)
    monkeypatch.setattr(paramiko.Transport, "set_keepalive", record_keepalive)
    with qtbot.waitSignal(trusted_pool.connected, timeout=10000) as result:
        trusted_pool.connect(sftp_server.host, sftp_server.port, "password", sftp_server.password, keepalive_s=7)
    transport = result.args[0]
    try:
        assert transport.is_authenticated()
        assert intervals == [7]
        assert threads and threads[0] != QApplication.instance().thread()
        with paramiko.SFTPClient.from_transport(transport) as sftp:
            assert "h264_25.mp4" in sftp.listdir("/media")
    finally:
        transport.close()


@pytest.mark.sftp
def test_wrong_password_reports_error_and_retry_connects(qtbot, trusted_pool, sftp_server):
    with qtbot.waitSignal(trusted_pool.error, timeout=10000) as failed:
        trusted_pool.connect(sftp_server.host, sftp_server.port, "password", "not-the-password")
    assert "Authentication failed" in failed.args[0]
    assert sftp_server.password not in failed.args[0]
    with qtbot.waitSignal(trusted_pool.connected, timeout=10000) as result:
        trusted_pool.connect(sftp_server.host, sftp_server.port, "password", sftp_server.password)
    result.args[0].close()


@pytest.mark.sftp
def test_unknown_host_key_is_never_accepted_implicitly(qtbot, sftp_server, tmp_path):
    pool = SshPool(KnownHosts(tmp_path / "missing_user", tmp_path / "missing_app"))
    with qtbot.waitSignal(pool.error, timeout=10000) as result:
        pool.connect(sftp_server.host, sftp_server.port, "password", sftp_server.password)
    assert "Unknown SSH host key" in result.args[0]


def test_invalid_ssh_connection_reports_error_without_worker(qtbot, tmp_path):
    pool = SshPool(KnownHosts(tmp_path / "missing_user", tmp_path / "missing_app"))
    with qtbot.waitSignal(pool.error):
        pool.connect("host name", 22, "user", "password")
    with qtbot.waitSignal(pool.error):
        pool.connect("host", 0, "user", "password")
    with qtbot.waitSignal(pool.error):
        pool.connect("host", 22, "user", "password", keepalive_s=0)
    assert pool.workers.activeThreadCount() == 0
