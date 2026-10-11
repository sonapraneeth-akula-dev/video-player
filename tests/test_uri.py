from types import SimpleNamespace

import keyring
import pytest

from vplayer.settings import ConnectionProfile, Settings
from vplayer.sftp import SftpUri, match_sftp_profile, parse_sftp_uri
from vplayer.ui.dialogs import ConnectDialog


@pytest.mark.parametrize(("value", "expected"), [
    ("sftp://viewer@host.example/media/movie.mp4", SftpUri("viewer", "host.example", 22, "/media/movie.mp4")),
    ("sftp://host.example:2222/a%20b/%E2%98%83.mkv", SftpUri(None, "host.example", 2222, "/a b/☃.mkv")),
    ("sftp://first%40last@[::1]:2200/f%2Fg", SftpUri("first@last", "::1", 2200, "/f/g")),
    ("sftp://HOST.EXAMPLE/", SftpUri(None, "host.example", 22, "/")),
])
def test_parse_valid_remote_file_uris(value, expected):
    assert parse_sftp_uri(value) == expected


@pytest.mark.parametrize(("value", "problem"), [
    ("file:///clip.mkv", "sftp://"),
    ("sftp:///movie.mkv", "host"),
    ("sftp://host.example", "path"),
    ("sftp://host.example:0/file", "port"),
    ("sftp://host.example:65536/file", "port"),
    ("sftp://host.example:xyz/file", "port"),
    ("sftp://host.example:/file", "port"),
    ("sftp://user:password@host.example/file", "Passwords"),
    ("sftp://host.example/file?secret=1", "query"),
    ("sftp://host.example/file#fragment", "fragment"),
    ("sftp://host.example/bad%Q1", "percent escape"),
    ("sftp://host.example/bad%FF", "UTF-8"),
    ("sftp://host.example/%00", "path"),
    ("sftp://@host.example/file", "username"),
    ("sftp://bad%2Fhost.example/file", "host"),
    ("sftp://[::1/file", "host"),
])
def test_malformed_uri_names_problem_without_echoing_credentials(value, problem):
    with pytest.raises(ValueError, match=problem) as failed:
        parse_sftp_uri(value)
    assert "password@host.example" not in str(failed.value)


def test_nontext_uri_rejected():
    with pytest.raises(TypeError, match="string"):
        parse_sftp_uri(None)


def test_profile_match_must_be_unique_and_user_specific():
    first = ConnectionProfile("91f53ff8-e93e-4c9f-8b48-fde4f68ded94", "HOST.example", 22, "alex", "password")
    second = ConnectionProfile("f73d408d-83e9-4942-b20e-9808b3992d9d", "host.example", 22, "sam", "agent")
    assert match_sftp_profile(parse_sftp_uri("sftp://alex@host.example/movie"), [first, second]) == first
    assert match_sftp_profile(parse_sftp_uri("sftp://host.example/movie"), [first, second]) is None
    assert match_sftp_profile(parse_sftp_uri("sftp://host.example:2222/movie"), [first]) is None
    assert match_sftp_profile(parse_sftp_uri("sftp://host.example/movie"), [first]) == first


def test_uri_uses_saved_profile_or_prefills_new_connection(qtbot, tmp_path, monkeypatch):
    settings = Settings(tmp_path / "settings.ini")
    profile = ConnectionProfile("91f53ff8-e93e-4c9f-8b48-fde4f68ded94", "host.example", 2222, "alex", "password")
    settings.save_connection(profile)
    monkeypatch.setattr(keyring, "get_keyring", lambda: SimpleNamespace(priority=5))
    monkeypatch.setattr(keyring, "get_password", lambda service, account: "keyring-secret")
    saved = ConnectDialog.for_sftp_uri("sftp://alex@HOST.EXAMPLE:2222/media/clip.mp4", settings=settings)
    qtbot.addWidget(saved)
    assert saved.profile_id == profile.id
    assert saved.profiles.currentData() == profile.id
    assert saved.password.text() == "keyring-secret"
    assert saved.remote_path == "/media/clip.mp4"
    fresh = ConnectDialog.for_sftp_uri("sftp://sam@other.example:2223/dir/a%20b.mkv", settings=settings)
    qtbot.addWidget(fresh)
    assert fresh.profiles.currentData() is None
    assert (fresh.host.text(), fresh.port.value(), fresh.user.text()) == ("other.example", 2223, "sam")
    assert fresh.password.text() == ""
    assert fresh.remote_path == "/dir/a b.mkv"
    assert b"keyring-secret" not in (tmp_path / "settings.ini").read_bytes()
