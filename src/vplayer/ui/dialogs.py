"""Dialogs for explicit SSH host-key confirmation."""

import base64
import hashlib
from collections.abc import Callable

import paramiko
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from vplayer.sftp import KnownHosts


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
