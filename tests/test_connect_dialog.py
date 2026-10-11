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


def test_profile_crud_stores_secrets_only_in_keyring(qtbot, tmp_path, monkeypatch):
    secrets = {}
    monkeypatch.setattr(keyring, "get_keyring", lambda: SimpleNamespace(priority=5))
    monkeypatch.setattr(keyring, "set_password", lambda service, account, secret: secrets.__setitem__(account, secret))
    monkeypatch.setattr(keyring, "get_password", lambda service, account: secrets.get(account))
    monkeypatch.setattr(keyring, "delete_password", lambda service, account: secrets.pop(account))
    settings = Settings(tmp_path / "settings.ini")
    dialog = ConnectDialog(settings=settings)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.host.setText("sftp.example")
    dialog.port.setValue(2222)
    dialog.user.setText("viewer")
    dialog.password.setText("sftp-private-password")
    dialog.save_secret.setChecked(True)
    dialog.save_profile.click()
    profile_id = dialog.profile_id
    assert dialog.profiles.currentData() == profile_id
    assert len(settings.connection_profiles()) == 1
    assert secrets == {f"{profile_id}/password": "sftp-private-password"}
    assert b"sftp-private-password" not in (tmp_path / "settings.ini").read_bytes()

    loaded = ConnectDialog(settings=Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(loaded)
    loaded.profiles.setCurrentIndex(loaded.profiles.findData(profile_id))
    assert (loaded.host.text(), loaded.port.value(), loaded.user.text()) == ("sftp.example", 2222, "viewer")
    assert loaded.password.text() == "sftp-private-password"
    assert loaded.password.echoMode() == QLineEdit.EchoMode.Password
    loaded.auth.setCurrentIndex(1)
    loaded.key_path.setText("/home/viewer/.ssh/id_ed25519")
    loaded.password.setText("private-key-passphrase")
    loaded.save_secret.setChecked(True)
    loaded.save_profile.click()
    assert secrets == {f"{profile_id}/key": "private-key-passphrase"}
    assert b"private-key-passphrase" not in (tmp_path / "settings.ini").read_bytes()
    assert settings.connection_profiles()[0].auth == "key"
    loaded.delete_profile.click()
    assert settings.connection_profiles() == []
    assert secrets == {}
    assert loaded.profiles.currentData() is None
    assert loaded.host.text() == ""


def test_profile_save_error_does_not_write_secret_to_ini(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: SimpleNamespace(priority=5))

    def reject_secret(*args):
        raise keyring.errors.PasswordSetError("OS keyring locked")

    monkeypatch.setattr(keyring, "set_password", reject_secret)
    messages = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: messages.append(args))
    settings = Settings(tmp_path / "settings.ini")
    dialog = ConnectDialog(settings=settings)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.host.setText("sftp.example")
    dialog.user.setText("viewer")
    dialog.password.setText("do-not-persist")
    dialog.save_secret.setChecked(True)
    dialog.save_profile.click()
    assert messages and "OS keyring locked" in str(messages[-1])
    assert settings.connection_profiles() == []
    assert not (tmp_path / "settings.ini").exists() or b"do-not-persist" not in (tmp_path / "settings.ini").read_bytes()


def test_unchecking_save_secret_removes_stored_profile_credential(qtbot, tmp_path, monkeypatch):
    secrets = {}
    monkeypatch.setattr(keyring, "get_keyring", lambda: SimpleNamespace(priority=5))
    monkeypatch.setattr(keyring, "set_password", lambda service, account, secret: secrets.__setitem__(account, secret))
    monkeypatch.setattr(keyring, "get_password", lambda service, account: secrets.get(account))
    monkeypatch.setattr(keyring, "delete_password", lambda service, account: secrets.pop(account))
    settings = Settings(tmp_path / "settings.ini")
    dialog = ConnectDialog(settings=settings)
    qtbot.addWidget(dialog)
    dialog.host.setText("sftp.example")
    dialog.user.setText("viewer")
    dialog.password.setText("keyring-only-secret")
    dialog.save_secret.setChecked(True)
    dialog.save_profile.click()
    assert secrets
    dialog.save_secret.setChecked(False)
    dialog.save_profile.click()
    assert secrets == {}
    assert len(settings.connection_profiles()) == 1
    restored = ConnectDialog(settings=Settings(tmp_path / "settings.ini"), profile_id=dialog.profile_id)
    qtbot.addWidget(restored)
    assert restored.password.text() == ""
    assert not restored.save_secret.isChecked()
