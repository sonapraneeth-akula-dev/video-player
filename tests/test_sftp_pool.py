import paramiko
import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog

from vplayer.sftp import KnownHosts, SshPool
from vplayer.ui.dialogs import ConnectDialog


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
    connected = []
    pool.connected.connect(lambda transport: connected.append(transport))
    with qtbot.waitSignal(pool.host_key_required, timeout=10000) as result:
        pool.connect(sftp_server.host, sftp_server.port, "password", sftp_server.password)
    assert result.args[:2] == [sftp_server.host, sftp_server.port]
    assert pool.known_hosts.classify(*result.args[:3]) == "unknown"
    assert not connected


@pytest.mark.sftp
def test_changed_key_requires_warning_and_rejection_prevents_authentication(
    qtbot, sftp_server, tmp_path, monkeypatch,
):
    from vplayer.ui.dialogs import HostKeyDialog

    known = KnownHosts(tmp_path / "missing_user", tmp_path / "app" / "known_hosts")
    old_key = paramiko.RSAKey.generate(1024)
    known.remember(sftp_server.host, sftp_server.port, old_key)
    original = known.app_path.read_bytes()
    pool = SshPool(known)
    warnings = []
    authenticated = []
    original_auth = paramiko.Transport.auth_password

    def record_auth(transport, *args, **kwargs):
        authenticated.append(True)
        return original_auth(transport, *args, **kwargs)

    def reject_warning(dialog):
        warnings.append(dialog.windowTitle())
        assert dialog.reject_button.isDefault()
        assert not dialog.accept_once.isDefault()
        assert not dialog.remember_button.isDefault()
        dialog.reject_button.click()
        return dialog.result()

    monkeypatch.setattr(paramiko.Transport, "auth_password", record_auth)
    monkeypatch.setattr(HostKeyDialog, "exec", reject_warning)
    dialog = ConnectDialog(pool=pool)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.host.setText(sftp_server.host)
    dialog.port.setValue(sftp_server.port)
    dialog.user.setText("password")
    dialog.password.setText(sftp_server.password)
    with qtbot.waitSignal(pool.host_key_required, timeout=10000):
        dialog.accept()
    qtbot.waitUntil(lambda: bool(warnings), timeout=10000)
    assert "Changed SSH host key" in warnings
    assert dialog.isVisible()
    assert not authenticated
    assert known.app_path.read_bytes() == original


@pytest.mark.sftp
def test_trust_changed_key_once_pins_retry_without_persisting(qtbot, sftp_server, tmp_path, monkeypatch):
    from vplayer.ui.dialogs import HostKeyDialog

    known = KnownHosts(tmp_path / "missing_user", tmp_path / "app" / "known_hosts")
    old_key = paramiko.RSAKey.generate(1024)
    known.remember(sftp_server.host, sftp_server.port, old_key)
    original = known.app_path.read_bytes()
    pool = SshPool(known)
    prompts = []

    def trust_once(dialog):
        prompts.append(dialog.windowTitle())
        dialog.accept_once.click()
        return dialog.result()

    monkeypatch.setattr(HostKeyDialog, "exec", trust_once)
    dialog = ConnectDialog(pool=pool)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.host.setText(sftp_server.host)
    dialog.port.setValue(sftp_server.port)
    dialog.user.setText("password")
    dialog.password.setText(sftp_server.password)
    with qtbot.waitSignal(dialog.connected, timeout=10000) as result:
        dialog.accept()
    try:
        assert result.args[0].is_authenticated()
        assert prompts == ["Changed SSH host key"]
        assert known.classify(sftp_server.host, sftp_server.port, result.args[0].get_remote_server_key()) == "changed"
        assert known.app_path.read_bytes() == original
    finally:
        result.args[0].close()


@pytest.mark.sftp
def test_remember_unknown_key_allows_later_connection_without_prompt(qtbot, sftp_server, tmp_path, monkeypatch):
    from vplayer.ui.dialogs import HostKeyDialog

    user_file = tmp_path / "missing_user"
    known = KnownHosts(user_file, tmp_path / "app" / "known_hosts")
    pool = SshPool(known)
    prompts = []

    def remember(dialog):
        prompts.append(dialog.windowTitle())
        dialog.remember_button.click()
        return dialog.result()

    monkeypatch.setattr(HostKeyDialog, "exec", remember)
    dialog = ConnectDialog(pool=pool)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.host.setText(sftp_server.host)
    dialog.port.setValue(sftp_server.port)
    dialog.user.setText("password")
    dialog.password.setText(sftp_server.password)
    with qtbot.waitSignal(dialog.connected, timeout=10000) as first:
        dialog.accept()
    server_key = first.args[0].get_remote_server_key()
    first.args[0].close()
    assert prompts == ["Unknown SSH host key"]
    assert not user_file.exists()
    assert KnownHosts(user_file, known.app_path).classify(
        sftp_server.host, sftp_server.port, server_key,
    ) == "trusted"
    with qtbot.waitSignal(pool.connected, timeout=10000) as second:
        pool.connect(sftp_server.host, sftp_server.port, "password", sftp_server.password)
    second.args[0].close()
    assert prompts == ["Unknown SSH host key"]


@pytest.mark.sftp
@pytest.mark.parametrize("pin_previous_key", [False, True])
def test_reconnect_with_changed_key_fails_without_prompt(qtbot, sftp_server, tmp_path, pin_previous_key):
    known = KnownHosts(tmp_path / "missing_user", tmp_path / "app" / "known_hosts")
    old_key = paramiko.RSAKey.generate(1024)
    known.remember(sftp_server.host, sftp_server.port, old_key)
    pool = SshPool(known)
    prompts = []
    pool.host_key_required.connect(lambda *args: prompts.append(args))
    with qtbot.waitSignal(pool.connection_failed, timeout=10000) as failed:
        pool.connect(
            sftp_server.host, sftp_server.port, "password", sftp_server.password,
            approved_key=old_key if pin_previous_key else None, reconnect=True,
        )
    assert "SSH host key" in failed.args[0]
    assert not prompts


@pytest.mark.sftp
def test_reconnect_with_unknown_key_fails_without_prompt(qtbot, sftp_server, tmp_path):
    pool = SshPool(KnownHosts(tmp_path / "missing_user", tmp_path / "missing_app"))
    prompts = []
    pool.host_key_required.connect(lambda *args: prompts.append(args))
    with qtbot.waitSignal(pool.connection_failed, timeout=10000) as failed:
        pool.connect(sftp_server.host, sftp_server.port, "password", sftp_server.password, reconnect=True)
    assert "Unknown SSH host key during reconnect" in failed.args[0]
    assert not prompts


@pytest.mark.sftp
def test_cancelled_connection_does_not_open_late_host_key_prompt(qtbot, sftp_server, tmp_path, monkeypatch):
    from vplayer.ui.dialogs import HostKeyDialog

    pool = SshPool(KnownHosts(tmp_path / "missing_user", tmp_path / "missing_app"))
    monkeypatch.setattr(HostKeyDialog, "exec", lambda dialog: pytest.fail("Prompt after cancellation"))
    dialog = ConnectDialog(pool=pool)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.host.setText(sftp_server.host)
    dialog.port.setValue(sftp_server.port)
    dialog.user.setText("password")
    dialog.password.setText(sftp_server.password)
    with qtbot.waitSignal(pool.host_key_required, timeout=10000):
        dialog.accept()
        dialog.reject()
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_invalid_ssh_connection_reports_error_without_worker(qtbot, tmp_path):
    pool = SshPool(KnownHosts(tmp_path / "missing_user", tmp_path / "missing_app"))
    with qtbot.waitSignal(pool.error):
        pool.connect("host name", 22, "user", "password")
    with qtbot.waitSignal(pool.error):
        pool.connect("host", 0, "user", "password")
    with qtbot.waitSignal(pool.error):
        pool.connect("host", 22, "user", "password", keepalive_s=0)
    with qtbot.waitSignal(pool.error):
        pool.connect("host", 22, "user", auth="key")
    assert pool.workers.activeThreadCount() == 0


@pytest.mark.sftp
def test_private_key_prompts_for_passphrase_and_can_retry(qtbot, trusted_pool, sftp_server):
    with qtbot.waitSignal(trusted_pool.passphrase_required, timeout=10000) as required:
        trusted_pool.connect(
            sftp_server.host, sftp_server.port, "key", auth="key", key_path=sftp_server.key,
        )
    assert required.args[0] == str(sftp_server.key)
    with qtbot.waitSignal(trusted_pool.error, timeout=10000) as failed:
        trusted_pool.connect(
            sftp_server.host, sftp_server.port, "key", auth="key",
            key_path=sftp_server.key, passphrase="wrong",
        )
    assert "Could not connect" in failed.args[0]
    with qtbot.waitSignal(trusted_pool.connected, timeout=10000) as success:
        trusted_pool.connect(
            sftp_server.host, sftp_server.port, "key", auth="key",
            key_path=sftp_server.key, passphrase=sftp_server.passphrase,
        )
    success.args[0].close()


@pytest.mark.sftp
def test_ssh_agent_tries_keys_without_leaking_private_key(qtbot, trusted_pool, sftp_server, monkeypatch):
    wrong_key = paramiko.RSAKey.generate(1024)
    agent_key = paramiko.RSAKey.from_private_key_file(str(sftp_server.agent_key))

    class FakeAgent:
        closed = False

        def get_keys(self):
            return (wrong_key, agent_key)

        def close(self):
            self.closed = True

    agent = FakeAgent()
    monkeypatch.setattr(paramiko, "Agent", lambda: agent)
    with qtbot.waitSignal(trusted_pool.connected, timeout=10000) as result:
        trusted_pool.connect(sftp_server.host, sftp_server.port, "agent", auth="agent")
    try:
        assert result.args[0].is_authenticated()
        assert agent.closed
    finally:
        result.args[0].close()


@pytest.mark.sftp
def test_missing_agent_keys_report_clear_error(qtbot, trusted_pool, sftp_server, monkeypatch):
    class EmptyAgent:
        def get_keys(self):
            return ()

        def close(self):
            pass

    monkeypatch.setattr(paramiko, "Agent", EmptyAgent)
    with qtbot.waitSignal(trusted_pool.error, timeout=10000) as result:
        trusted_pool.connect(sftp_server.host, sftp_server.port, "agent", auth="agent")
    assert "No SSH agent keys available" in result.args[0]


@pytest.mark.sftp
def test_encrypted_key_prompts_in_dialog_and_retries(qtbot, trusted_pool, sftp_server, monkeypatch):
    prompts = []

    def prompt(*args):
        prompts.append(args)
        return sftp_server.passphrase, True

    monkeypatch.setattr(QInputDialog, "getText", prompt)
    dialog = ConnectDialog(pool=trusted_pool)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.host.setText(sftp_server.host)
    dialog.port.setValue(sftp_server.port)
    dialog.user.setText("key")
    dialog.auth.setCurrentIndex(1)
    dialog.key_path.setText(str(sftp_server.key))
    with qtbot.waitSignal(dialog.connected, timeout=10000) as result:
        dialog.accept()
    try:
        assert prompts and prompts[0][2].endswith(str(sftp_server.key))
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert result.args[0].is_authenticated()
    finally:
        result.args[0].close()


@pytest.mark.sftp
def test_cancelled_passphrase_prompt_keeps_connection_dialog_open(qtbot, trusted_pool, sftp_server, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *args: ("", False))
    dialog = ConnectDialog(pool=trusted_pool)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.host.setText(sftp_server.host)
    dialog.port.setValue(sftp_server.port)
    dialog.user.setText("key")
    dialog.auth.setCurrentIndex(1)
    dialog.key_path.setText(str(sftp_server.key))
    with qtbot.waitSignal(trusted_pool.passphrase_required, timeout=10000):
        dialog.accept()
    assert dialog.isVisible()
    assert dialog.password.text() == ""
