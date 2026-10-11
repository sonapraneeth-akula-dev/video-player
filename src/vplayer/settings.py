"""Validated INI settings backed by Qt."""

import logging
import math
import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings

log = logging.getLogger(__name__)
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ConnectionProfile:
    id: str
    host: str
    port: int
    user: str
    auth: str
    key_path: str = ""

    def __post_init__(self):
        if not isinstance(self.id, str) or str(uuid.UUID(self.id)) != self.id:
            raise ValueError("Invalid connection profile ID")
        if not isinstance(self.host, str) or not self.host or any(char.isspace() for char in self.host):
            raise ValueError("Enter a host without whitespace")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("Connection port must be between 1 and 65535")
        if not isinstance(self.user, str) or not self.user or any(char.isspace() for char in self.user):
            raise ValueError("Enter a username without whitespace")
        if self.auth not in ("password", "key", "agent"):
            raise ValueError("Invalid connection authentication method")
        if not isinstance(self.key_path, str):
            raise TypeError("Invalid private key path")
        if self.auth == "key" and not self.key_path:
            raise ValueError("Choose a private key file")


class Settings:
    def __init__(self, path: Path | None = None):
        self.store = (
            QSettings(str(path), QSettings.Format.IniFormat)
            if path is not None
            else QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "vplayer", "vplayer")
        )
        self.seek_short_s = 5
        self.seek_long_s = 60
        self.speed_step = 0.05

    def _bounded_int(self, key: str, default: int, minimum: int, maximum: int) -> int:
        value = self.store.value(key)
        if value is None:
            return default
        try:
            if not isinstance(value, (str, int)) or isinstance(value, bool):
                raise TypeError("setting must be an integer")
            number = int(value)
            if minimum <= number <= maximum:
                return number
        except (TypeError, ValueError):
            pass
        log.warning("Invalid %s setting %r; using %s", key, value, default)
        self.store.setValue(key, default)
        return default

    def load(self) -> None:
        version = self._bounded_int("schema_version", 0, 0, 2**31 - 1)
        if version < SCHEMA_VERSION:
            self.store.setValue("schema_version", SCHEMA_VERSION)
        self.seek_short_s = self._bounded_int("playback/seek_short_s", 5, 1, 600)
        self.seek_long_s = self._bounded_int("playback/seek_long_s", 60, 1, 3600)
        value = self.store.value("playback/speed_step", 0.05)
        try:
            if isinstance(value, bool):
                raise TypeError("speed step must be a number")
            step = float(value)
            if not math.isfinite(step) or not 0.01 <= step <= 1.0:
                raise ValueError("speed step out of range")
        except (TypeError, ValueError):
            log.warning("Invalid playback/speed_step setting %r; using 0.05", value)
            step = 0.05
            self.store.setValue("playback/speed_step", step)
        self.speed_step = step
        self.store.sync()
        if self.store.status() != QSettings.Status.NoError:
            raise OSError(f"Could not read/write settings: {self.store.fileName()}")

    def connection_profiles(self) -> list[ConnectionProfile]:
        profiles = []
        self.store.beginGroup("connections")
        try:
            for profile_id in self.store.childGroups():
                self.store.beginGroup(profile_id)
                try:
                    port = self.store.value("port")
                    if isinstance(port, bool) or not isinstance(port, (str, int)):
                        raise TypeError("Invalid connection port")
                    profile = ConnectionProfile(
                        profile_id,
                        self.store.value("host", ""),
                        int(port),
                        self.store.value("user", ""),
                        self.store.value("auth", ""),
                        self.store.value("key_path", ""),
                    )
                    profiles.append(profile)
                except (TypeError, ValueError) as error:
                    log.warning("Skipping invalid connection profile %s: %s", profile_id, error)
                finally:
                    self.store.endGroup()
        finally:
            self.store.endGroup()
        return sorted(profiles, key=lambda profile: (profile.host.casefold(), profile.user.casefold(), profile.port))

    def save_connection(self, profile: ConnectionProfile) -> None:
        if not isinstance(profile, ConnectionProfile):
            raise TypeError("Expected a connection profile")
        prefix = f"connections/{profile.id}"
        self.store.remove(prefix)
        for name in ("host", "port", "user", "auth", "key_path"):
            self.store.setValue(f"{prefix}/{name}", getattr(profile, name))
        self.store.sync()
        if self.store.status() != QSettings.Status.NoError:
            raise OSError(f"Could not save connection profile: {self.store.fileName()}")

    def delete_connection(self, profile_id: str) -> None:
        if not isinstance(profile_id, str) or str(uuid.UUID(profile_id)) != profile_id:
            raise ValueError("Invalid connection profile ID")
        self.store.remove(f"connections/{profile_id}")
        self.store.sync()
        if self.store.status() != QSettings.Status.NoError:
            raise OSError(f"Could not delete connection profile: {self.store.fileName()}")
