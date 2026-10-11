import logging

from PySide6.QtCore import QSettings

from vplayer.settings import Settings


def test_settings_migrate_and_repair_invalid_values(tmp_path, caplog):
    path = tmp_path / "settings.ini"
    raw = QSettings(str(path), QSettings.Format.IniFormat)
    raw.setValue("schema_version", "bad")
    raw.setValue("playback/seek_short_s", "0")
    raw.setValue("playback/seek_long_s", "bad")
    raw.sync()

    settings = Settings(path)
    with caplog.at_level(logging.WARNING):
        settings.load()
    assert settings.seek_short_s == 5
    assert settings.seek_long_s == 60
    assert int(raw.value("schema_version")) == 1
    assert int(raw.value("playback/seek_short_s")) == 5
    assert int(raw.value("playback/seek_long_s")) == 60
    assert "Invalid playback/seek_long_s" in caplog.text


def test_settings_keep_newer_schema_and_valid_seeks(tmp_path):
    path = tmp_path / "newer.ini"
    raw = QSettings(str(path), QSettings.Format.IniFormat)
    raw.setValue("schema_version", 2)
    raw.setValue("playback/seek_short_s", 11)
    raw.setValue("playback/seek_long_s", 120)
    raw.sync()
    settings = Settings(path)
    settings.load()
    assert (settings.seek_short_s, settings.seek_long_s) == (11, 120)
    assert int(raw.value("schema_version")) == 2


def test_fractional_and_boolean_seek_settings_fall_back(tmp_path):
    settings = Settings(tmp_path / "settings.ini")
    settings.store.setValue("playback/seek_short_s", 2.5)
    settings.store.setValue("playback/seek_long_s", True)
    settings.load()
    assert (settings.seek_short_s, settings.seek_long_s) == (5, 60)
