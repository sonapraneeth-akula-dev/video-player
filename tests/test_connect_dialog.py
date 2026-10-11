from types import SimpleNamespace

import keyring
import pytest
from PySide6.QtWidgets import QDialog, QLineEdit, QMessageBox

from vplayer.settings import Settings
from vplayer.ui.dialogs import ConnectDialog


def test_connect_dialog_saves_secret_only_in_keyring(qtbot, tmp_path, monkeypatch):
    saved = []
    monkeypatch.setattr(keyring, "get_keyring", lambda: SimpleNamespace(priority=5))
    monkeypatch.setattr(keyring, "set_password", lambda *args: saved.append(args))
    settings = Settings(tmp_path / "settings.ini")
    settings.load()
    dialog = ConnectDialog("91f53ff8-e93e-4c9f-8b48-fde4f68ded94")
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.host.setText("sftp.example")
    dialog.user.setText("viewer")
    dialog.password.setText("private-password-value")
    dialog.save_secret.setChecked(True)
    assert dialog.port.value() == 22
    assert dialog.password.echoMode() == QLineEdit.EchoMode.Password
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert saved == [("vplayer", "91f53ff8-e93e-4c9f-8b48-fde4f68ded94/password", "private-password-value")]
    assert b"private-password-value" not in (tmp_path / "settings.ini").read_bytes()


def test_without_keyring_backend_save_secret_is_disabled(qtbot, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: SimpleNamespace(priority=0))
    dialog = ConnectDialog()
    qtbot.addWidget(dialog)
    assert not dialog.save_secret.isEnabled()
    assert "No OS keyring backend" in dialog.save_secret.toolTip()
    dialog.auth.setCurrentIndex(1)
    assert dialog.key_path.isEnabled()
    assert not dialog.save_secret.isEnabled()
    dialog.auth.setCurrentIndex(2)
    assert not dialog.password.isEnabled()


def test_save_error_and_invalid_connection_keep_dialog_open(qtbot, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: SimpleNamespace(priority=5))

    def reject_save(*args):
        raise keyring.errors.PasswordSetError("locked")

    monkeypatch.setattr(keyring, "set_password", reject_save)
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args))
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args))
    dialog = ConnectDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.accept()
    assert dialog.isVisible()
    dialog.host.setText("sftp.example")
    dialog.user.setText("viewer")
    dialog.password.setText("private-password-value")
    dialog.save_secret.setChecked(True)
    dialog.accept()
    assert dialog.isVisible()
    assert len(errors) == 2
    assert "locked" in str(errors[-1])


def test_auth_choice_does_not_store_agent_secret(qtbot, monkeypatch):
    calls = []
    monkeypatch.setattr(keyring, "get_keyring", lambda: SimpleNamespace(priority=5))
    monkeypatch.setattr(keyring, "set_password", lambda *args: calls.append(args))
    dialog = ConnectDialog()
    qtbot.addWidget(dialog)
    dialog.host.setText("sftp.example")
    dialog.user.setText("viewer")
    dialog.save_secret.setChecked(True)
    dialog.auth.setCurrentIndex(2)
    assert not dialog.save_secret.isChecked()
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert calls == []


def test_rejects_invalid_profile_id():
    with pytest.raises(ValueError):
        ConnectDialog("../not-a-uuid")
