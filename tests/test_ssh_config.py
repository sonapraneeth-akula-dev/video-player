from pathlib import Path

import paramiko
import pytest

from vplayer.sftp import ResolvedSshAlias, resolve_alias


def write_config(path: Path, text: str):
    path.write_text(text, encoding="utf-8")


def test_alias_resolves_only_supported_settings_and_honors_explicit_overrides(tmp_path):
    path = tmp_path / "config"
    write_config(path, """
Host archive
    HostName media.example
    Port 2222
    User operator
    IdentityFile ~/.ssh/alias_key
    ProxyJump gateway
    HostKeyAlias spoofed.example
""")
    result = resolve_alias("archive", config_path=path)
    assert result.host == "media.example"
    assert result.port == 2222
    assert result.user == "operator"
    assert Path(result.key_path) == Path.home() / ".ssh" / "alias_key"
    assert "ProxyJump" in result.notice
    assert "HostKeyAlias" in result.notice
    overridden = resolve_alias("archive", config_path=path, port=2022, user="typed", key_path="typed.key")
    assert (overridden.host, overridden.port, overridden.user, overridden.key_path) == (
        "media.example", 2022, "typed", "typed.key",
    )


def test_missing_config_uses_alias_and_explicit_values(tmp_path):
    assert resolve_alias("missing", config_path=tmp_path / "absent") == ResolvedSshAlias(
        "missing", 22, None, None, None,
    )
    assert resolve_alias("missing", config_path=tmp_path / "absent", port=2200, user="user").port == 2200


def test_match_exec_blocks_are_skipped_without_running_commands(tmp_path, monkeypatch):
    path = tmp_path / "config"
    marker = tmp_path / "must-not-exist"
    write_config(path, f"""
Match exec "touch {marker}"
    HostName attacker.example
    User unsafe
Host safe
    HostName safe.example
    User viewer
Match !exec "touch {marker}"
    Port 9999
Host another
    HostName another.example
""")
    monkeypatch.setattr(paramiko.config.invoke, "run", lambda *args, **kwargs: pytest.fail("Match exec was run"))
    result = resolve_alias("safe", config_path=path)
    assert (result.host, result.user, result.port) == ("safe.example", "viewer", 22)
    assert "Match exec blocks skipped" in result.notice
    assert resolve_alias("another", config_path=path).host == "another.example"
    assert not marker.exists()


def test_canonicalization_is_removed_before_lookup(tmp_path, monkeypatch):
    path = tmp_path / "config"
    write_config(path, """
Host alias
    CanonicalizeHostname yes
    CanonicalDomains untrusted.example
    HostName actual.example
    Port 2200
""")
    monkeypatch.setattr(paramiko.SSHConfig, "canonicalize", lambda *args: pytest.fail("DNS canonicalization ran"))
    result = resolve_alias("alias", config_path=path)
    assert (result.host, result.port) == ("actual.example", 2200)
    assert "CanonicalizeHostname" in result.notice
    assert "CanonicalDomains" in result.notice


def test_safe_match_host_directive_still_applies(tmp_path):
    path = tmp_path / "config"
    write_config(path, "Match host alias\n    Port 2200\nHost alias\n    HostName media.example\n")
    result = resolve_alias("alias", config_path=path)
    assert (result.host, result.port, result.notice) == ("media.example", 2200, None)


@pytest.mark.parametrize(("text", "problem"), [
    ("Host alias\n    unparseable\n", "Couldn't read ~/.ssh/config"),
    ("Host alias\n    Port invalid\n", "Couldn't read ~/.ssh/config"),
    ("Match exec 'unterminated\n    HostName bad.example\n", "Couldn't read ~/.ssh/config"),
])
def test_bad_config_falls_back_with_visible_notice(tmp_path, text, problem):
    path = tmp_path / "config"
    write_config(path, text)
    result = resolve_alias("alias", config_path=path, user="typed")
    assert (result.host, result.port, result.user) == ("alias", 22, "typed")
    assert problem in result.notice


def test_invalid_utf8_config_falls_back_with_notice(tmp_path):
    path = tmp_path / "config"
    path.write_bytes(b"\xff")
    result = resolve_alias("alias", config_path=path)
    assert result.host == "alias"
    assert "Couldn't read ~/.ssh/config" in result.notice


@pytest.mark.parametrize("options", [
    {"alias": "bad host"},
    {"port": 0},
    {"port": 65536},
    {"user": "bad user"},
    {"key_path": ""},
])
def test_invalid_alias_input_is_rejected(options, tmp_path):
    alias = options.pop("alias", "alias")
    with pytest.raises(ValueError):
        resolve_alias(alias, config_path=tmp_path / "absent", **options)
