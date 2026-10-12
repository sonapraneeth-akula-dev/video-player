"""SFTP host-key trust and bounded in-memory remote reads."""

import logging
import os
import re
import shlex
import tempfile
import threading
import weakref
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlsplit

import paramiko
from PySide6.QtCore import QObject, QStandardPaths, QThreadPool, Signal

from vplayer.settings import ConnectionProfile

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SftpUri:
    user: str | None
    host: str
    port: int
    path: str


def parse_sftp_uri(uri: str) -> SftpUri:
    if not isinstance(uri, str):
        raise TypeError("SFTP URI must be a string")
    if re.search(r"%(?![0-9a-fA-F]{2})", uri):
        raise ValueError("Malformed percent escape in SFTP URI")
    try:
        parsed = urlsplit(uri)
        host = parsed.hostname
    except ValueError as error:
        raise ValueError("Invalid SFTP URI host") from error
    if parsed.scheme.lower() != "sftp":
        raise ValueError("SFTP URI must start with sftp://")
    if not host:
        raise ValueError("SFTP URI is missing a host")
    if parsed.password is not None:
        raise ValueError("Passwords in SFTP URIs are not allowed")
    if parsed.query or parsed.fragment:
        raise ValueError("SFTP URI must not contain a query or fragment")
    if not parsed.path:
        raise ValueError("SFTP URI is missing an absolute path")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Invalid SFTP URI port") from error
    if parsed.netloc.endswith(":") or (port is not None and not 1 <= port <= 65535):
        raise ValueError("Invalid SFTP URI port")
    try:
        host = unquote(host, encoding="utf-8", errors="strict")
        user = unquote(parsed.username, encoding="utf-8", errors="strict") if parsed.username is not None else None
        path = unquote(parsed.path, encoding="utf-8", errors="strict")
    except UnicodeError as error:
        raise ValueError("Invalid UTF-8 in SFTP URI") from error
    if any(char.isspace() for char in host) or any(char in host for char in ("/", "\\", "\x00")):
        raise ValueError("Invalid SFTP URI host")
    if user is not None and (not user or any(char.isspace() for char in user) or "\x00" in user):
        raise ValueError("Invalid SFTP URI username")
    if "\x00" in path:
        raise ValueError("Invalid SFTP URI path")
    return SftpUri(user, host, port or 22, path)


def match_sftp_profile(uri: SftpUri, profiles: Iterable[ConnectionProfile]) -> ConnectionProfile | None:
    matches = [
        profile for profile in profiles
        if profile.host.casefold() == uri.host.casefold() and profile.port == uri.port
        and (uri.user is None or profile.user == uri.user)
    ]
    return matches[0] if len(matches) == 1 else None


@dataclass(frozen=True)
class ResolvedSshAlias:
    host: str
    port: int
    user: str | None
    key_path: str | None
    notice: str | None


def resolve_alias(
    alias: str, *, config_path: Path | None = None,
    port: int | None = None, user: str | None = None, key_path: str | None = None,
) -> ResolvedSshAlias:
    if not isinstance(alias, str) or not alias or any(char.isspace() for char in alias):
        raise ValueError("SSH alias must be a host name without whitespace")
    if port is not None and (isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535):
        raise ValueError("SSH port must be between 1 and 65535")
    if user is not None and (not isinstance(user, str) or not user or any(char.isspace() for char in user)):
        raise ValueError("SSH username must be nonempty and contain no whitespace")
    if key_path is not None and (not isinstance(key_path, str) or not key_path):
        raise ValueError("SSH private key path must be nonempty")
    path = config_path or Path.home() / ".ssh" / "config"
    fallback = ResolvedSshAlias(alias, port or 22, user, key_path, None)
    if not path.exists():
        return fallback
    try:
        lines = []
        skipped = set()
        names = {}
        in_exec_block = False
        for line in path.read_text(encoding="utf-8").splitlines():
            directive = re.match(r"\s*(\w+)(?:\s*=\s*|\s+)(.+)", line)
            if directive:
                name, value = directive.group(1), directive.group(2)
                names[name.lower()] = name
                if name.lower() in ("host", "match"):
                    in_exec_block = name.lower() == "match" and any(
                        token.lstrip("!").lower() == "exec" for token in shlex.split(value)
                    )
                    if in_exec_block:
                        skipped.add("Match exec blocks skipped")
                if name.lower().startswith("canonical"):
                    skipped.add(name)
                    continue
            if not in_exec_block:
                lines.append(line)
        found = paramiko.SSHConfig.from_text("\n".join(lines)).lookup(alias)
        ignored = [names.get(key, key) for key in set(found) - {"hostname", "port", "user", "identityfile"}]
        skipped.update(ignored)
        resolved_port = port if port is not None else int(found.get("port", 22))
        if not 1 <= resolved_port <= 65535:
            raise ValueError("Invalid port in SSH config")
        host = found.get("hostname", alias)
        resolved_user = user if user is not None else found.get("user")
        if not host or any(char.isspace() for char in host):
            raise ValueError("Invalid HostName in SSH config")
        if resolved_user is not None and (not resolved_user or any(char.isspace() for char in resolved_user)):
            raise ValueError("Invalid User in SSH config")
        keys = found.get("identityfile", [])
        identity = key_path if key_path is not None else (keys[0] if keys else None)
        notice = f"Ignored SSH config settings: {', '.join(sorted(skipped))}" if skipped else None
        return ResolvedSshAlias(host, resolved_port, resolved_user, identity, notice)
    except (OSError, UnicodeError, paramiko.SSHException, ValueError, TypeError, KeyError) as error:
        return ResolvedSshAlias(alias, port or 22, user, key_path, f"Couldn't read ~/.ssh/config: {error}")


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
        self._sessions: weakref.WeakKeyDictionary[paramiko.Transport, tuple] = weakref.WeakKeyDictionary()
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
        *, notify: bool = True, on_transport: Callable[[paramiko.Transport], None] | None = None,
    ) -> paramiko.Transport | None:
        transport = None
        try:
            transport = paramiko.Transport((host, port))
            if on_transport is not None:
                on_transport(transport)
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
        except paramiko.PasswordRequiredException as error:
            if transport is not None:
                transport.close()
            if not notify:
                raise paramiko.SSHException("Private key requires a passphrase") from error
            self.passphrase_required.emit(str(key_path))
            return
        except (OSError, EOFError, paramiko.SSHException) as error:
            if transport is not None:
                transport.close()
            if not notify:
                raise
            self.error.emit(f"Could not connect to {host}:{port}: {error}")
            return
        if notify:
            self._sessions[transport] = (
                host, port, user, password, auth, key_path, passphrase, keepalive_s, key,
            )
            self.connected.emit(transport)
        return transport

    def reopen_transport(self, previous: paramiko.Transport, cancel: threading.Event) -> paramiko.Transport:
        session = self._sessions.get(previous)
        if session is None:
            raise OSError("No authenticated SSH session available for reconnect")
        done = threading.Event()
        result: list[paramiko.Transport | BaseException] = []
        opening: list[paramiko.Transport] = []

        def track(transport: paramiko.Transport) -> None:
            opening.append(transport)
            if cancel.is_set():
                transport.close()

        def worker() -> None:
            try:
                transport = self._connect(*session, reconnect=True, notify=False, on_transport=track)
                if transport is None:
                    raise OSError("SSH reconnect did not return a transport")
                if cancel.is_set():
                    transport.close()
                else:
                    result.append(transport)
            except Exception as error:  # noqa: BLE001 - propagate worker failure to the reader
                result.append(error)
            finally:
                done.set()

        self.workers.start(worker)
        while not done.wait(0.05):
            if cancel.is_set():
                if opening:
                    opening[0].close()
                raise OSError("SFTP stream cancelled")
        if cancel.is_set():
            if result and isinstance(result[0], paramiko.Transport):
                result[0].close()
            raise OSError("SFTP stream cancelled")
        if isinstance(result[0], BaseException):
            raise result[0]
        self._sessions[result[0]] = session
        return result[0]


class SftpStream(QObject):
    reconnecting = Signal(int)
    reconnected = Signal()
    connection_failed = Signal(int)
    BLOCK_SIZE = 4 * 1024 * 1024
    CHUNK_SIZE = 32 * 1024

    def __init__(
        self, remote_file: paramiko.SFTPFile, *,
        reopen: Callable[[threading.Event], paramiko.SFTPFile] | None = None,
        retry_max: int = 6,
    ):
        super().__init__()
        if isinstance(retry_max, bool) or not isinstance(retry_max, int) or not 0 <= retry_max <= 20:
            raise ValueError("SFTP retry count must be between 0 and 20")
        if reopen is not None and not callable(reopen):
            raise TypeError("SFTP reopen callback must be callable")
        size = remote_file.stat().st_size
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError("Remote file size must be a nonnegative integer")
        self.remote_file = remote_file
        self.reopen = reopen
        self.retry_max = retry_max
        self._cancel_event = threading.Event()
        self._size = size
        self._position = 0
        self._block_offset = -1
        self._block = b""
        self._closed = False
        self._cancelled = False
        self.failed = False

    def size(self) -> int:
        return self._size

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def read(self, count: int) -> bytes:
        if self._cancelled:
            raise OSError("SFTP stream cancelled")
        if self._closed:
            raise ValueError("SFTP stream is closed")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("Read size must be a nonnegative integer")
        if count == 0 or self._position >= self._size:
            return b""
        offset = self._position - self._position % self.BLOCK_SIZE
        if offset != self._block_offset:
            length = min(self.BLOCK_SIZE, self._size - offset)
            chunks = [
                (offset + start, min(self.CHUNK_SIZE, length - start))
                for start in range(0, length, self.CHUNK_SIZE)
            ]
            block = self._read_block(chunks, length, offset)
            if self._cancelled:
                raise OSError("SFTP stream cancelled")
            if self._closed:
                raise ValueError("SFTP stream is closed")
            self._block = block
            self._block_offset = offset
        start = self._position - offset
        data = self._block[start:start + min(count, len(self._block) - start)]
        if self._cancelled:
            raise OSError("SFTP stream cancelled")
        if self._closed:
            raise ValueError("SFTP stream is closed")
        self._position += len(data)
        return data

    def _read_block(self, chunks: list[tuple[int, int]], length: int, offset: int) -> bytes:
        last_error: OSError | EOFError | paramiko.SSHException | None = None
        for attempt in range(self.retry_max + 1):
            if attempt:
                self.reconnecting.emit(attempt)
                if self._cancel_event.wait(min(2 ** (attempt - 1), 30)):
                    raise OSError("SFTP stream cancelled") from last_error
                replacement = None
                try:
                    replacement = self.reopen(self._cancel_event)
                    if self._cancelled:
                        raise OSError("SFTP stream cancelled")
                    if replacement.stat().st_size != self._size:
                        raise ValueError("Remote file changed during reconnect")
                    old = self.remote_file
                    self.remote_file = replacement
                    replacement = None
                    try:
                        old.close()
                    except (OSError, EOFError, ValueError, paramiko.SSHException) as error:
                        log.warning("Could not close disconnected SFTP file: %s", error)
                except ValueError:
                    if replacement is not None:
                        replacement.close()
                    raise
                except (OSError, EOFError, paramiko.SSHException):
                    if replacement is not None:
                        replacement.close()
                    if self._cancelled:
                        raise OSError("SFTP stream cancelled") from last_error
                    if attempt == self.retry_max:
                        self.failed = True
                        self.connection_failed.emit(self._position)
                        raise
                    continue
            try:
                block = b"".join(self.remote_file.readv(chunks, max_concurrent_prefetch_requests=64))
                if len(block) != length:
                    raise EOFError(f"Expected {length} SFTP bytes at offset {offset}, got {len(block)}")
            except Exception as error:
                if self._cancelled:
                    raise OSError("SFTP stream cancelled") from error
                if not isinstance(error, (OSError, EOFError, paramiko.SSHException)):
                    raise
                last_error = error
                if self.reopen is None or attempt == self.retry_max:
                    self.failed = True
                    self.connection_failed.emit(self._position)
                    raise
                continue
            if self._cancelled:
                raise OSError("SFTP stream cancelled")
            if attempt:
                self.reconnected.emit()
            return block
        raise RuntimeError("SFTP retry loop ended without a result")

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if self._cancelled:
            raise OSError("SFTP stream cancelled")
        if self._closed:
            raise ValueError("SFTP stream is closed")
        if (
            isinstance(offset, bool) or not isinstance(offset, int)
            or isinstance(whence, bool) or not isinstance(whence, int)
            or whence not in (
            os.SEEK_SET, os.SEEK_CUR, os.SEEK_END,
            )
        ):
            raise ValueError("Invalid SFTP seek")
        base = (0, self._position, self._size)[whence]
        position = base + offset
        if position < 0:
            raise ValueError("Cannot seek before the start of a remote file")
        self._position = position
        return position

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._block = b""
            self.remote_file.close()

    def cancel(self) -> None:
        self._cancelled = True
        self._cancel_event.set()
        self.close()
