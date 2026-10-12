"""Validated INI settings backed by Qt."""

import logging
import math
import os
import uuid
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths

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
        self.pitch_correction = True
        self.resume_enabled = False
        self.skip_frames = 10
        self.readahead_mb = 64
        self.backbuffer_mb = 256
        self.snapshot_dir = Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation),
        ) / "vplayer"
        self.jpeg_quality = 90

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

    def _bool(self, key: str, default: bool) -> bool:
        value = self.store.value(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        log.warning("Invalid %s setting %r; using %s", key, value, default)
        self.store.setValue(key, default)
        return default

    def load(self) -> None:
        version = self._bounded_int("schema_version", 0, 0, 2**31 - 1)
        if version < SCHEMA_VERSION:
            self.store.setValue("schema_version", SCHEMA_VERSION)
        self.seek_short_s = self._bounded_int("playback/seek_short_s", 5, 1, 600)
        self.seek_long_s = self._bounded_int("playback/seek_long_s", 60, 1, 3600)
        self.skip_frames = self._bounded_int("playback/skip_frames", 10, 2, 1000)
        self.readahead_mb = self._bounded_int("network/readahead_mb", 64, 16, 64)
        self.backbuffer_mb = self._bounded_int("network/backbuffer_mb", 256, 0, 256)
        snapshot_dir = self.store.value("snapshot/dir")
        if snapshot_dir is not None:
            if isinstance(snapshot_dir, str) and snapshot_dir.strip() and Path(snapshot_dir).is_absolute():
                self.snapshot_dir = Path(snapshot_dir)
            else:
                log.warning("Invalid snapshot/dir setting %r; using %s", snapshot_dir, self.snapshot_dir)
                self.store.setValue("snapshot/dir", str(self.snapshot_dir))
        self.jpeg_quality = self._bounded_int("snapshot/jpeg_quality", 90, 50, 100)
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
        self.pitch_correction = self._bool("playback/pitch_correction", True)
        self.resume_enabled = self._bool("resume/enabled", False)
        self.store.sync()
        if self.store.status() != QSettings.Status.NoError:
            raise OSError(f"Could not read/write settings: {self.store.fileName()}")

    def set_pitch_correction(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("Pitch correction must be a boolean")
        self.store.setValue("playback/pitch_correction", enabled)
        self.store.sync()
        if self.store.status() != QSettings.Status.NoError:
            raise OSError(f"Could not save pitch correction: {self.store.fileName()}")
        self.pitch_correction = enabled

    def set_resume_enabled(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("Resume enabled must be a boolean")
        self.store.setValue("resume/enabled", enabled)
        self.store.sync()
        if self.store.status() != QSettings.Status.NoError:
            raise OSError(f"Could not save resume preference: {self.store.fileName()}")
        self.resume_enabled = enabled

    @staticmethod
    def _resume_key(file: Path) -> str:
        if not isinstance(file, Path) or not file.is_absolute():
            raise ValueError("Resume path must be an absolute local file path")
        return f"resume/positions/{sha256(os.path.normcase(str(file.resolve())).encode('utf-8')).hexdigest()}"

    def resume_position(self, file: Path) -> float | None:
        key = self._resume_key(file)
        value = self.store.value(key)
        if value is None:
            return None
        try:
            if isinstance(value, bool) or not isinstance(value, (str, float, int)):
                raise TypeError("Invalid resume position")
            position = float(value)
            if not math.isfinite(position) or position < 0:
                raise ValueError("Invalid resume position")
            return position
        except (TypeError, ValueError):
            log.warning("Invalid %s setting %r; removing it", key, value)
            self.store.remove(key)
            self.store.sync()
            if self.store.status() != QSettings.Status.NoError:
                raise OSError(f"Could not repair resume position: {self.store.fileName()}")
            return None

    def set_resume_position(self, file: Path, position: float) -> None:
        key = self._resume_key(file)
        if isinstance(position, bool) or not isinstance(position, (float, int)) or not math.isfinite(position) or position < 0:
            raise ValueError("Resume position must be a nonnegative finite number")
        self.store.setValue(key, position)
        self.store.sync()
        if self.store.status() != QSettings.Status.NoError:
            raise OSError(f"Could not save resume position: {self.store.fileName()}")

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
