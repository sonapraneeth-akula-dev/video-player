"""Dialogs for explicit SSH host-key confirmation."""

import base64
import hashlib
import uuid
from collections.abc import Callable

import keyring
import paramiko
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from vplayer.sftp import KnownHosts


class ConnectDialog(QDialog):
    def __init__(self, profile_id: str | None = None, parent=None):
        super().__init__(parent)
        self.profile_id = str(uuid.UUID(profile_id)) if profile_id is not None else str(uuid.uuid4())
        self.setWindowTitle("Connect to SFTP")
        form = QFormLayout()
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
        connect.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(connect)
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

    def _auth_changed(self):
        method = self.auth.currentData()
        self.key_path.setEnabled(method == "key")
        self.password.setEnabled(method != "agent")
        self.save_secret.setEnabled(self._keyring_available and method != "agent")
        if method == "agent":
            self.save_secret.setChecked(False)

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
        super().accept()


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
