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
    passphrase_required = Signal(str)
    host_key_required = Signal(str, int, object, object)


class SshPool:
    def __init__(self, known_hosts: KnownHosts):
        self.known_hosts = known_hosts
        self.workers = QThreadPool()
        self._signals = _PoolSignals()
        self.connected = self._signals.connected
        self.error = self._signals.error
        self.connection_failed = self._signals.error
        self.passphrase_required = self._signals.passphrase_required
        self.host_key_required = self._signals.host_key_required

    def connect(
        self, host: str, port: int, user: str, password: str | None = None, *,
        auth: Literal["password", "key", "agent"] = "password",
        key_path: str | Path | None = None,
        passphrase: str | None = None,
        keepalive_s: int = 15,
        approved_key: paramiko.PKey | None = None,
        reconnect: bool = False,
    ) -> None:
        if (
            not isinstance(host, str) or not host or any(char.isspace() for char in host)
            or isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535
            or not isinstance(user, str) or not user or any(char.isspace() for char in user)
            or auth not in ("password", "key", "agent")
            or (auth == "password" and not isinstance(password, str))
            or (auth == "key" and (not isinstance(key_path, (str, Path)) or not str(key_path)))
            or (passphrase is not None and not isinstance(passphrase, str))
            or isinstance(keepalive_s, bool) or not isinstance(keepalive_s, int)
            or not 5 <= keepalive_s <= 300
            or (approved_key is not None and not isinstance(approved_key, paramiko.PKey))
            or not isinstance(reconnect, bool)
        ):
            self.error.emit("Invalid SSH connection parameters")
            return
        self.workers.start(
            lambda: self._connect(
                host, port, user, password, auth, key_path, passphrase, keepalive_s, approved_key, reconnect,
            ),
        )

    def _connect(
        self, host: str, port: int, user: str, password: str | None,
        auth: Literal["password", "key", "agent"], key_path: str | Path | None,
        passphrase: str | None, keepalive_s: int, approved_key: paramiko.PKey | None,
        reconnect: bool,
    ) -> None:
        transport = None
        try:
            transport = paramiko.Transport((host, port))
            transport.start_client(timeout=10)
            key = transport.get_remote_server_key()
            trust = self.known_hosts.classify(host, port, key)
            if approved_key is not None and key != approved_key:
                raise paramiko.SSHException(f"SSH host key changed since approval for {host}:{port}")
            if trust != "trusted" and approved_key is None:
                if reconnect:
                    raise paramiko.SSHException(f"{trust.capitalize()} SSH host key during reconnect for {host}:{port}")
                transport.close()
                self.host_key_required.emit(host, port, key, transport.close)
                return
            if auth == "password":
                transport.auth_password(user, password)
            elif auth == "key":
                path = str(Path(key_path).expanduser())
                last_error = paramiko.SSHException("Unsupported private key")
                for key_type in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
                    try:
                        private_key = key_type.from_private_key_file(path, password=passphrase)
                        break
                    except paramiko.PasswordRequiredException:
                        raise
                    except paramiko.SSHException as error:
                        last_error = error
                else:
                    raise last_error
                transport.auth_publickey(user, private_key)
            else:
                agent = paramiko.Agent()
                try:
                    available = agent.get_keys()
                    if not available:
                        raise paramiko.AuthenticationException("No SSH agent keys available")
                    for candidate in available:
                        try:
                            transport.auth_publickey(user, candidate)
                        except paramiko.AuthenticationException:
                            continue
                        if transport.is_authenticated():
                            break
                    else:
                        raise paramiko.AuthenticationException("SSH agent keys were rejected")
                finally:
                    agent.close()
            if not transport.is_authenticated():
                raise paramiko.AuthenticationException("Authentication failed")
            transport.set_keepalive(keepalive_s)
        except paramiko.PasswordRequiredException:
            if transport is not None:
                transport.close()
            self.passphrase_required.emit(str(key_path))
            return
        except (OSError, EOFError, paramiko.SSHException) as error:
            if transport is not None:
                transport.close()
            self.error.emit(f"Could not connect to {host}:{port}: {error}")
            return
        self.connected.emit(transport)
