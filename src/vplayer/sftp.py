"""SFTP host-key trust shared by connection and reconnect flows."""

import os
import tempfile
from pathlib import Path
from typing import Literal

import paramiko
from PySide6.QtCore import QObject, QStandardPaths, QThreadPool, Signal


class KnownHosts:
    def __init__(self, user_path: Path | None = None, app_path: Path | None = None):
        self.user_path = user_path or Path.home() / ".ssh" / "known_hosts"
        self.app_path = app_path or Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
        ) / "known_hosts"
        self.user = paramiko.HostKeys()
        self.app = paramiko.HostKeys()
        for path, keys in ((self.user_path, self.user), (self.app_path, self.app)):
            if path.exists():
                keys.load(str(path))

    def classify(self, host: str, port: int, key: paramiko.PKey) -> Literal["trusted", "changed", "unknown"]:
        if not isinstance(host, str) or not host or any(char.isspace() for char in host):
            raise ValueError("Host must be a nonempty name without whitespace")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        if not isinstance(key, paramiko.PKey):
            raise TypeError("Host key must be a Paramiko public key")
        name = host if port == 22 else f"[{host}]:{port}"
        found = False
        for keys in (self.user, self.app):
            matches = keys.lookup(name)
            if matches is None:
                continue
            # Paramiko's mapping exposes only the first key of each algorithm.
            for entry in matches._entries:
                found = True
                if entry.key == key:
                    return "trusted"
        return "changed" if found else "unknown"

    def remember(self, host: str, port: int, key: paramiko.PKey) -> None:
        self.classify(host, port, key)
        name = host if port == 22 else f"[{host}]:{port}"
        self.app_path.parent.mkdir(parents=True, exist_ok=True)
        updated = paramiko.HostKeys(str(self.app_path)) if self.app_path.exists() else paramiko.HostKeys()
        updated.add(name, key.get_name(), key)
        fd, temporary = tempfile.mkstemp(prefix=".known_hosts-", dir=self.app_path.parent)
        os.close(fd)
        try:
            updated.save(temporary)
            os.replace(temporary, self.app_path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        self.app = updated


class _PoolSignals(QObject):
    connected = Signal(object)
    error = Signal(str)


class SshPool:
    def __init__(self, known_hosts: KnownHosts):
        self.known_hosts = known_hosts
        self.workers = QThreadPool()
        self._signals = _PoolSignals()
        self.connected = self._signals.connected
        self.error = self._signals.error

    def connect(self, host: str, port: int, user: str, password: str, *, keepalive_s: int = 15) -> None:
        if (
            not isinstance(host, str) or not host or any(char.isspace() for char in host)
            or isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535
            or not isinstance(user, str) or not user or any(char.isspace() for char in user)
            or not isinstance(password, str)
            or isinstance(keepalive_s, bool) or not isinstance(keepalive_s, int)
            or not 5 <= keepalive_s <= 300
        ):
            self.error.emit("Invalid SSH connection parameters")
            return
        self.workers.start(lambda: self._connect(host, port, user, password, keepalive_s))

    def _connect(self, host: str, port: int, user: str, password: str, keepalive_s: int) -> None:
        transport = None
        try:
            transport = paramiko.Transport((host, port))
            transport.start_client(timeout=10)
            key = transport.get_remote_server_key()
            trust = self.known_hosts.classify(host, port, key)
            if trust != "trusted":
                raise paramiko.SSHException(f"{trust.capitalize()} SSH host key for {host}:{port}")
            transport.auth_password(user, password)
            if not transport.is_authenticated():
                raise paramiko.AuthenticationException("Authentication failed")
            transport.set_keepalive(keepalive_s)
        except (OSError, EOFError, paramiko.SSHException) as error:
            if transport is not None:
                transport.close()
            self.error.emit(f"Could not connect to {host}:{port}: {error}")
            return
        self.connected.emit(transport)
