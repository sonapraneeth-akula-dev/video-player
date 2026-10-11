import base64
import hashlib
from pathlib import Path

import paramiko
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox

from vplayer.sftp import KnownHosts
from vplayer.ui.dialogs import HostKeyDialog


@pytest.fixture
def keys():
    return tuple(paramiko.RSAKey.generate(1024) for _ in range(3))


def write_hosts(path: Path, *entries: tuple[str, paramiko.PKey]) -> None:
    path.write_text(
        "".join(f"{host} {key.get_name()} {key.get_base64()}\n" for host, key in entries),
        encoding="utf-8",
    )


def test_user_and_app_files_keep_multiple_keys_of_same_type(tmp_path, keys):
    old, accepted, changed = keys
    user_file = tmp_path / "user_known_hosts"
    app_file = tmp_path / "app_known_hosts"
    write_hosts(user_file, ("host.example", old))
    write_hosts(app_file, ("host.example", accepted))
    original = user_file.read_bytes()
    known = KnownHosts(user_file, app_file)
    assert known.classify("host.example", 22, old) == "trusted"
    assert known.classify("host.example", 22, accepted) == "trusted"
    assert known.classify("host.example", 22, changed) == "changed"
    assert known.classify("host.example", 22, paramiko.ECDSAKey.generate(bits=256)) == "changed"
    assert known.classify("unknown.example", 22, changed) == "unknown"
    assert user_file.read_bytes() == original


def test_hasched_hosts_and_nondefault_ports_do_not_cross_trust(tmp_path, keys):
    old, accepted, changed = keys
    user_file = tmp_path / "user_known_hosts"
    app_file = tmp_path / "app_known_hosts"
    hashed = paramiko.HostKeys.hash_host("[host.example]:2222")
    write_hosts(user_file, (hashed, old), ("host.example", old))
    write_hosts(app_file, ("[host.example]:2222", accepted))
    known = KnownHosts(user_file, app_file)
    assert known.classify("host.example", 2222, old) == "trusted"
    assert known.classify("host.example", 2222, accepted) == "trusted"
    assert known.classify("host.example", 2222, changed) == "changed"
    assert known.classify("host.example", 22, accepted) == "changed"
    assert known.classify("host.example", 2223, old) == "unknown"


def test_same_file_duplicate_key_types_and_multi_host_entries(tmp_path, keys):
    old, accepted, changed = keys
    user_file = tmp_path / "user_known_hosts"
    write_hosts(user_file, ("one.example,two.example", old), ("two.example", accepted))
    known = KnownHosts(user_file, tmp_path / "missing")
    assert known.classify("one.example", 22, old) == "trusted"
    assert known.classify("two.example", 22, old) == "trusted"
    assert known.classify("two.example", 22, accepted) == "trusted"
    assert known.classify("two.example", 22, changed) == "changed"


def test_invalid_host_or_port_fails_closed(tmp_path, keys):
    known = KnownHosts(tmp_path / "missing_user", tmp_path / "missing_app")
    for host, port in (("", 22), ("host name", 22), ("example", 0), ("example", 65536), ("example", True)):
        with pytest.raises(ValueError):
            known.classify(host, port, keys[0])
    with pytest.raises(TypeError):
        known.classify("example", 22, None)


def test_host_key_dialog_accept_once_does_not_write_and_rejects_by_default(qtbot, tmp_path, keys):
    known = KnownHosts(tmp_path / "missing_user", tmp_path / "app" / "known_hosts")
    closed = []
    dialog = HostKeyDialog(known, "host.example", 2222, keys[0], lambda: closed.append(True))
    qtbot.addWidget(dialog)
    dialog.show()
    fingerprint = base64.b64encode(hashlib.sha256(keys[0].asbytes()).digest()).decode().rstrip("=")
    assert f"SHA256:{fingerprint}" in dialog.fingerprint.text()
    assert dialog.fingerprint.textFormat() == Qt.TextFormat.PlainText
    assert dialog.reject_button.isDefault()
    assert "unknown" in dialog.windowTitle().lower()
    dialog.accept_once.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert not closed
    assert not known.app_path.exists()
    assert known.classify("host.example", 2222, keys[0]) == "unknown"
    other = HostKeyDialog(known, "host.example", 2222, keys[0], lambda: closed.append(True))
    qtbot.addWidget(other)
    other.show()
    QTest.keyClick(other, Qt.Key.Key_Escape)
    assert other.result() == QDialog.DialogCode.Rejected
    assert closed == [True]


def test_remember_writes_only_app_file_and_persists_trust(qtbot, tmp_path, keys):
    user_file = tmp_path / "user_known_hosts"
    write_hosts(user_file, ("host.example", keys[0]))
    original = user_file.read_bytes()
    known = KnownHosts(user_file, tmp_path / "app" / "known_hosts")
    dialog = HostKeyDialog(known, "host.example", 22, keys[1], lambda: None)
    qtbot.addWidget(dialog)
    dialog.show()
    assert "changed" in dialog.windowTitle().lower()
    dialog.remember_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert user_file.read_bytes() == original
    assert KnownHosts(user_file, known.app_path).classify("host.example", 22, keys[1]) == "trusted"
    assert not list(known.app_path.parent.glob(".known_hosts-*"))


def test_failed_save_keeps_existing_trust_and_dialog_open(qtbot, tmp_path, keys, monkeypatch):
    app_file = tmp_path / "app" / "known_hosts"
    app_file.parent.mkdir()
    write_hosts(app_file, ("host.example", keys[0]))
    original = app_file.read_bytes()
    known = KnownHosts(tmp_path / "missing_user", app_file)
    closed = []
    dialog = HostKeyDialog(known, "host.example", 22, keys[1], lambda: closed.append(True))
    qtbot.addWidget(dialog)
    dialog.show()
    errors = []
    def fail_replace(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr("vplayer.sftp.os.replace", fail_replace)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args))
    dialog.remember_button.click()
    assert dialog.isVisible()
    assert errors and "disk unavailable" in str(errors[0])
    assert app_file.read_bytes() == original
    assert known.classify("host.example", 22, keys[1]) == "changed"
    assert not list(app_file.parent.glob(".known_hosts-*"))
    dialog.reject_button.click()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert closed == [True]
