"""Dialogs for explicit SSH host-key confirmation."""

import base64
import hashlib
import uuid
from collections.abc import Callable

import keyring
import paramiko
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from vplayer.settings import ConnectionProfile, Settings
from vplayer.sftp import KnownHosts, SshPool, match_sftp_profile, parse_sftp_uri


class ConnectDialog(QDialog):
    connected = Signal(object)

    @classmethod
    def for_sftp_uri(
        cls, uri: str, *, settings: Settings | None = None, pool: SshPool | None = None, parent=None,
    ) -> "ConnectDialog":
        parsed = parse_sftp_uri(uri)
        settings = settings or Settings()
        profile = match_sftp_profile(parsed, settings.connection_profiles())
        dialog = cls(profile_id=profile.id if profile is not None else None, settings=settings, pool=pool, parent=parent)
        if profile is None:
            dialog.host.setText(parsed.host)
            dialog.port.setValue(parsed.port)
            dialog.user.setText(parsed.user or "")
        dialog.remote_path = parsed.path
        return dialog

    def __init__(
        self, profile_id: str | None = None, parent=None, *,
        pool: SshPool | None = None, settings: Settings | None = None,
    ):
        super().__init__(parent)
        self.pool = pool
        self.settings = settings or Settings()
        self._profiles: dict[str, ConnectionProfile] = {}
        self._approved_host_key: tuple[str, int, paramiko.PKey] | None = None
        self._connecting = False
        self.profile_id = str(uuid.UUID(profile_id)) if profile_id is not None else str(uuid.uuid4())
        self.setWindowTitle("Connect to SFTP")
        form = QFormLayout()
        self.profiles = QComboBox(self)
        self.profiles.setAccessibleName("Saved SSH connection")
        form.addRow("Profile", self.profiles)
        self.host = QLineEdit(self)
        self.host.setAccessibleName("SSH host")
        form.addRow("Host", self.host)
        self.port = QSpinBox(self)
        self.port.setRange(1, 65535)
        self.port.setValue(22)
        self.port.setAccessibleName("SSH port")
        form.addRow("Port", self.port)
        self.user = QLineEdit(self)
        self.user.setAccessibleName("SSH username")
        form.addRow("User", self.user)
        self.auth = QComboBox(self)
        for label, value in (("Password", "password"), ("Private key", "key"), ("SSH agent", "agent")):
            self.auth.addItem(label, value)
        self.auth.setAccessibleName("Authentication method")
        form.addRow("Authentication", self.auth)
        self.key_path = QLineEdit(self)
        self.key_path.setAccessibleName("Private key path")
        form.addRow("Private key path", self.key_path)
        self.password = QLineEdit(self)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setAccessibleName("Password or key passphrase")
        form.addRow("Password or passphrase", self.password)
        self.save_secret = QCheckBox("Save secret in OS keyring", self)
        form.addRow(self.save_secret)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        connect = QPushButton("Connect", self)
        cancel = QPushButton("Cancel", self)
        self.save_profile = QPushButton("Save profile", self)
        self.delete_profile = QPushButton("Delete profile", self)
        connect.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        self.save_profile.clicked.connect(self._save_profile)
        self.delete_profile.clicked.connect(self._delete_profile)
        buttons.addWidget(connect)
        buttons.addWidget(self.save_profile)
        buttons.addWidget(self.delete_profile)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        try:
            self._keyring_available = keyring.get_keyring().priority >= 1
        except RuntimeError:
            self._keyring_available = False
        if not self._keyring_available:
            self.save_secret.setToolTip("No OS keyring backend is available; the secret will not be saved.")
        self.auth.currentIndexChanged.connect(self._auth_changed)
        self._auth_changed()
        self._refresh_profiles()
        self.profiles.currentIndexChanged.connect(self._select_profile)
        if profile_id is not None and profile_id in self._profiles:
            self._select_profile()
        if pool is not None:
            pool.passphrase_required.connect(self._request_passphrase)
            pool.error.connect(self._connection_error)
            pool.connected.connect(self._connection_succeeded)
            pool.host_key_required.connect(self._confirm_host_key)

    def _auth_changed(self):
        method = self.auth.currentData()
        self.key_path.setEnabled(method == "key")
        self.password.setEnabled(method != "agent")
        self.save_secret.setEnabled(self._keyring_available and method != "agent")
        if method == "agent":
            self.save_secret.setChecked(False)

    def _set_connecting(self, connecting: bool):
        self._connecting = connecting
        self.profiles.setEnabled(not connecting)
        self.save_profile.setEnabled(not connecting)
        self.delete_profile.setEnabled(not connecting and self.profiles.currentData() is not None)

    def _refresh_profiles(self):
        self._profiles = {profile.id: profile for profile in self.settings.connection_profiles()}
        self.profiles.blockSignals(True)
        try:
            self.profiles.clear()
            self.profiles.addItem("New connection", None)
            for profile in self._profiles.values():
                self.profiles.addItem(f"{profile.user}@{profile.host}:{profile.port}", profile.id)
            index = self.profiles.findData(self.profile_id)
            self.profiles.setCurrentIndex(max(index, 0))
        finally:
            self.profiles.blockSignals(False)
        self.delete_profile.setEnabled(self.profiles.currentData() is not None)

    def _select_profile(self):
        profile_id = self.profiles.currentData()
        self.delete_profile.setEnabled(profile_id is not None)
        self._approved_host_key = None
        self.password.clear()
        self.save_secret.setChecked(False)
        if profile_id is None:
            self.profile_id = str(uuid.uuid4())
            self.host.clear()
            self.port.setValue(22)
            self.user.clear()
            self.auth.setCurrentIndex(0)
            self.key_path.clear()
            return
        profile = self._profiles[profile_id]
        self.profile_id = profile.id
        self.host.setText(profile.host)
        self.port.setValue(profile.port)
        self.user.setText(profile.user)
        self.auth.setCurrentIndex(self.auth.findData(profile.auth))
        self.key_path.setText(profile.key_path)
        if self._keyring_available and profile.auth != "agent":
            try:
                secret = keyring.get_password("vplayer", f"{profile.id}/{profile.auth}")
            except (keyring.errors.KeyringError, RuntimeError) as error:
                QMessageBox.warning(self, "Could not read saved secret", str(error))
                return
            if secret is not None:
                self.password.setText(secret)
                self.save_secret.setChecked(True)

    def _save_profile(self):
        try:
            profile = ConnectionProfile(
                self.profile_id, self.host.text().strip(), self.port.value(),
                self.user.text().strip(), self.auth.currentData(),
                self.key_path.text().strip() if self.auth.currentData() == "key" else "",
            )
        except (TypeError, ValueError) as error:
            QMessageBox.warning(self, "Invalid SSH connection", str(error))
            return
        account = f"{profile.id}/{profile.auth}"
        try:
            if self.save_secret.isChecked():
                keyring.set_password("vplayer", account, self.password.text())
            elif (
                self._keyring_available and profile.auth != "agent"
                and keyring.get_password("vplayer", account) is not None
            ):
                keyring.delete_password("vplayer", account)
            old = self._profiles.get(profile.id)
            if (
                old is not None and old.auth != profile.auth and old.auth != "agent"
                and self._keyring_available
                and keyring.get_password("vplayer", f"{profile.id}/{old.auth}") is not None
            ):
                keyring.delete_password("vplayer", f"{profile.id}/{old.auth}")
            self.settings.save_connection(profile)
        except (OSError, keyring.errors.KeyringError, RuntimeError) as error:
            QMessageBox.critical(self, "Could not save connection profile", str(error))
            return
        self._refresh_profiles()

    def _delete_profile(self):
        profile_id = self.profiles.currentData()
        if profile_id is None:
            return
        try:
            if self._keyring_available:
                for auth in ("password", "key"):
                    account = f"{profile_id}/{auth}"
                    if keyring.get_password("vplayer", account) is not None:
                        keyring.delete_password("vplayer", account)
            self.settings.delete_connection(profile_id)
        except (OSError, keyring.errors.KeyringError, RuntimeError) as error:
            QMessageBox.critical(self, "Could not delete connection profile", str(error))
            return
        self.profile_id = str(uuid.uuid4())
        self._refresh_profiles()
        self._select_profile()

    def accept(self):
        host = self.host.text().strip()
        user = self.user.text().strip()
        if not host or any(char.isspace() for char in host) or not user or any(char.isspace() for char in user):
            QMessageBox.warning(self, "Invalid SSH connection", "Enter a host and username without whitespace.")
            return
        if self.auth.currentData() == "key" and not self.key_path.text().strip():
            QMessageBox.warning(self, "Invalid SSH connection", "Choose a private key file.")
            return
        if self.save_secret.isChecked():
            try:
                keyring.set_password("vplayer", f"{self.profile_id}/{self.auth.currentData()}", self.password.text())
            except (keyring.errors.KeyringError, RuntimeError) as error:
                QMessageBox.critical(self, "Could not save secret", str(error))
                return
        if self.pool is not None:
            method = self.auth.currentData()
            approval = self._approved_host_key
            self._set_connecting(True)
            self.pool.connect(
                host, self.port.value(), user,
                password=self.password.text() if method == "password" else None,
                auth=method,
                key_path=self.key_path.text() if method == "key" else None,
                passphrase=(self.password.text() or None) if method == "key" else None,
                approved_key=approval[2] if approval is not None and approval[:2] == (host, self.port.value()) else None,
            )
            return
        super().accept()

    def _confirm_host_key(self, host: str, port: int, key: paramiko.PKey, close_transport: Callable[[], None]):
        if not self._connecting or not self.isVisible() or (host, port) != (self.host.text().strip(), self.port.value()):
            close_transport()
            return
        self._set_connecting(False)
        dialog = HostKeyDialog(self.pool.known_hosts, host, port, key, close_transport, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._approved_host_key = (host, port, key)
            self.accept()

    def _request_passphrase(self, key_path: str):
        if not self._connecting:
            return
        self._set_connecting(False)
        value, accepted = QInputDialog.getText(
            self, "Private key passphrase", f"Passphrase for {key_path}",
            QLineEdit.EchoMode.Password,
        )
        if accepted:
            self.password.setText(value)
            self.accept()

    def _connection_error(self, message: str):
        if not self._connecting:
            return
        self._set_connecting(False)
        QMessageBox.warning(self, "SSH connection failed", message)

    def _connection_succeeded(self, transport: paramiko.Transport):
        if not self._connecting:
            transport.close()
            return
        self._set_connecting(False)
        self._approved_host_key = None
        self.connected.emit(transport)
        super().accept()

    def reject(self):
        self._set_connecting(False)
        self._approved_host_key = None
        super().reject()

class HostKeyDialog(QDialog):
    def __init__(
        self, known: KnownHosts, host: str, port: int, key: paramiko.PKey,
        close_transport: Callable[[], None], parent=None,
    ):
        super().__init__(parent)
        self.known = known
        self.host = host
        self.port = port
        self.key = key
        self.close_transport = close_transport
        changed = known.classify(host, port, key) == "changed"
        self.setWindowTitle("Changed SSH host key" if changed else "Unknown SSH host key")
        layout = QVBoxLayout(self)
        if changed:
            warning = QLabel("Warning: this host's key has changed. Verify its fingerprint before trusting it.", self)
            warning.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(warning)
        fingerprint = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode("ascii").rstrip("=")
        self.fingerprint = QLabel(f"{host}:{port}\n{key.get_name()}\nSHA256:{fingerprint}", self)
        self.fingerprint.setTextFormat(Qt.TextFormat.PlainText)
        self.fingerprint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.fingerprint)
        buttons = QHBoxLayout()
        self.reject_button = QPushButton("Reject", self)
        self.accept_once = QPushButton("Trust once", self)
        self.remember_button = QPushButton("Trust and remember", self)
        self.reject_button.setDefault(True)
        self.reject_button.clicked.connect(self.reject)
        self.accept_once.clicked.connect(self.accept)
        self.remember_button.clicked.connect(self._remember)
        for button in (self.reject_button, self.accept_once, self.remember_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def reject(self):
        self.close_transport()
        super().reject()

    def _remember(self):
        try:
            self.known.remember(self.host, self.port, self.key)
        except OSError as error:
            QMessageBox.critical(self, "Could not save SSH host key", str(error))
            return
        self.accept()
