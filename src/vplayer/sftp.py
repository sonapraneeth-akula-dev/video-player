"""SFTP host-key trust shared by connection and reconnect flows."""

from pathlib import Path
from typing import Literal

import paramiko
from PySide6.QtCore import QStandardPaths


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
