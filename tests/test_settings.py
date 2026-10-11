import logging

import pytest
from PySide6.QtCore import QSettings

from vplayer.settings import ConnectionProfile, Settings


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


def test_speed_step_validation_and_custom_value(tmp_path, caplog):
    settings = Settings(tmp_path / "settings.ini")
    settings.store.setValue("playback/speed_step", "0.1")
    settings.load()
    assert settings.speed_step == 0.1
    for invalid in ("nan", "inf", "0.001", "1.01", "bad"):
        settings.store.setValue("playback/speed_step", invalid)
        with caplog.at_level(logging.WARNING):
            settings.load()
        assert settings.speed_step == 0.05
        assert float(settings.store.value("playback/speed_step")) == 0.05
    assert "Invalid playback/speed_step" in caplog.text


def test_remote_buffer_settings_are_bounded(tmp_path, caplog):
    settings = Settings(tmp_path / "settings.ini")
    settings.store.setValue("network/readahead_mb", 16)
    settings.store.setValue("network/backbuffer_mb", 0)
    settings.load()
    assert (settings.readahead_mb, settings.backbuffer_mb) == (16, 0)
    settings.store.setValue("network/readahead_mb", 15)
    settings.store.setValue("network/backbuffer_mb", 257)
    with caplog.at_level(logging.WARNING):
        settings.load()
    assert (settings.readahead_mb, settings.backbuffer_mb) == (64, 256)
    assert "Invalid network/readahead_mb" in caplog.text
    assert "Invalid network/backbuffer_mb" in caplog.text


def test_connection_profile_create_update_read_delete_without_secrets(tmp_path):
    path = tmp_path / "settings.ini"
    settings = Settings(path)
    profile_id = "91f53ff8-e93e-4c9f-8b48-fde4f68ded94"
    first = ConnectionProfile(profile_id, "sftp.example", 2222, "viewer", "password")
    settings.save_connection(first)
    assert Settings(path).connection_profiles() == [first]
    updated = ConnectionProfile(profile_id, "sftp.example", 2223, "viewer", "key", "/home/viewer/.ssh/id_ed25519")
    settings.save_connection(updated)
    assert Settings(path).connection_profiles() == [updated]
    settings.delete_connection(profile_id)
    assert Settings(path).connection_profiles() == []


def test_invalid_connection_profiles_are_skipped_with_warning(tmp_path, caplog):
    settings = Settings(tmp_path / "settings.ini")
    settings.store.setValue("connections/not-a-uuid/host", "bad")
    settings.store.setValue("connections/91f53ff8-e93e-4c9f-8b48-fde4f68ded94/port", "wrong")
    settings.store.sync()
    with caplog.at_level(logging.WARNING):
        assert settings.connection_profiles() == []
    assert caplog.text.count("Skipping invalid connection profile") == 2


def test_connection_profile_rejects_invalid_identity_and_port():
    with pytest.raises(ValueError):
        ConnectionProfile("../profile", "host", 22, "user", "password")
    with pytest.raises(ValueError):
        ConnectionProfile("91f53ff8-e93e-4c9f-8b48-fde4f68ded94", "host", 0, "user", "password")
