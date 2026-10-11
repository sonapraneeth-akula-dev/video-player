from pathlib import Path

import paramiko
import pytest

from vplayer.sftp import KnownHosts


@pytest.fixture
def keys():
    return tuple(paramiko.RSAKey.generate(1024) for _ in range(3))


def write_hosts(path: Path, *entries: tuple[str, paramiko.PKey]) -> None:
    path.write_text(
        "".join(f"{host} {key.get_name()} {key.get_base64()}\n" for host, key in entries),
        encoding="utf-8",
    )


def test_user_and_app_files_keep_multiple_keys_of_same_type(tmp_path, keys):
    old, accepted, changed = keys
    user_file = tmp_path / "user_known_hosts"
    app_file = tmp_path / "app_known_hosts"
    write_hosts(user_file, ("host.example", old))
    write_hosts(app_file, ("host.example", accepted))
    original = user_file.read_bytes()
    known = KnownHosts(user_file, app_file)
    assert known.classify("host.example", 22, old) == "trusted"
    assert known.classify("host.example", 22, accepted) == "trusted"
    assert known.classify("host.example", 22, changed) == "changed"
    assert known.classify("host.example", 22, paramiko.ECDSAKey.generate(bits=256)) == "changed"
    assert known.classify("unknown.example", 22, changed) == "unknown"
    assert user_file.read_bytes() == original


def test_hasched_hosts_and_nondefault_ports_do_not_cross_trust(tmp_path, keys):
    old, accepted, changed = keys
    user_file = tmp_path / "user_known_hosts"
    app_file = tmp_path / "app_known_hosts"
    hashed = paramiko.HostKeys.hash_host("[host.example]:2222")
    write_hosts(user_file, (hashed, old), ("host.example", old))
    write_hosts(app_file, ("[host.example]:2222", accepted))
    known = KnownHosts(user_file, app_file)
    assert known.classify("host.example", 2222, old) == "trusted"
    assert known.classify("host.example", 2222, accepted) == "trusted"
    assert known.classify("host.example", 2222, changed) == "changed"
    assert known.classify("host.example", 22, accepted) == "changed"
    assert known.classify("host.example", 2223, old) == "unknown"


def test_same_file_duplicate_key_types_and_multi_host_entries(tmp_path, keys):
    old, accepted, changed = keys
    user_file = tmp_path / "user_known_hosts"
    write_hosts(user_file, ("one.example,two.example", old), ("two.example", accepted))
    known = KnownHosts(user_file, tmp_path / "missing")
    assert known.classify("one.example", 22, old) == "trusted"
    assert known.classify("two.example", 22, old) == "trusted"
    assert known.classify("two.example", 22, accepted) == "trusted"
    assert known.classify("two.example", 22, changed) == "changed"


def test_invalid_host_or_port_fails_closed(tmp_path, keys):
    known = KnownHosts(tmp_path / "missing_user", tmp_path / "missing_app")
    for host, port in (("", 22), ("host name", 22), ("example", 0), ("example", 65536), ("example", True)):
        with pytest.raises(ValueError):
            known.classify(host, port, keys[0])
    with pytest.raises(TypeError):
        known.classify("example", 22, None)
