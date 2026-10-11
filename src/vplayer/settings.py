"""Validated INI settings backed by Qt."""

import logging
import math
from pathlib import Path

from PySide6.QtCore import QSettings

log = logging.getLogger(__name__)
SCHEMA_VERSION = 1


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
