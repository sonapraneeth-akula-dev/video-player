import hashlib
import io
import tarfile

import pytest

from scripts import fetch_libmpv


def test_fetch_installs_only_verified_dll(tmp_path, monkeypatch):
    dll = b"test libmpv"
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        info = tarfile.TarInfo("libmpv-2.dll")
        info.size = len(dll)
        tar.addfile(info, io.BytesIO(dll))
    contents = archive.getvalue()
    destination = tmp_path / "vendor" / "libmpv-2.dll"
    monkeypatch.setattr(fetch_libmpv.sys, "platform", "win32")
    monkeypatch.setattr(fetch_libmpv, "DESTINATION", destination)
    monkeypatch.setattr(fetch_libmpv, "ARCHIVE_SHA256", hashlib.sha256(contents).hexdigest())
    monkeypatch.setattr(fetch_libmpv, "DLL_SHA256", hashlib.sha256(dll).hexdigest())
    monkeypatch.setattr(fetch_libmpv.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(contents))

    fetch_libmpv.main()
    assert destination.read_bytes() == dll

    monkeypatch.setattr(fetch_libmpv, "ARCHIVE_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        fetch_libmpv.main()
    assert destination.read_bytes() == dll


def test_verify_sha256_rejects_tampering(tmp_path):
    archive = tmp_path / "archive.7z"
    archive.write_bytes(b"original")
    expected = hashlib.sha256(b"original").hexdigest()
    fetch_libmpv.verify_sha256(archive, expected)
    archive.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        fetch_libmpv.verify_sha256(archive, expected)
