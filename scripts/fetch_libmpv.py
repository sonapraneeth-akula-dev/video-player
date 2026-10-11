"""Fetch the Windows libmpv binary used by development and packaging."""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ARCHIVE = "mpv-dev-x86_64-20261011-git-accb7b2821.7z"
URL = f"https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/20261011/{ARCHIVE}"
ARCHIVE_SHA256 = "cf63b4ce66e03e5e70acf2648cbc3177656c77c5b9583e16d83efc58801182b7"
DLL_SHA256 = "e023856d0d2a96c66e75098c290dfd83b66a1c87740bb58152864e53e74f5ffb"
DESTINATION = Path(__file__).resolve().parents[1] / "vendor" / "libmpv-2.dll"


def verify_sha256(path: Path, expected: str) -> None:
    with path.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch for {path.name}: expected {expected}, got {actual}")


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Windows only; on Ubuntu install libmpv1 from apt")

    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        archive = Path(temp) / ARCHIVE
        with urllib.request.urlopen(URL, timeout=60) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        verify_sha256(archive, ARCHIVE_SHA256)
        subprocess.run(["tar", "-xf", str(archive), "-C", temp, "libmpv-2.dll"], check=True)
        dll = Path(temp) / "libmpv-2.dll"
        verify_sha256(dll, DLL_SHA256)
        os.replace(dll, DESTINATION)
    print(f"Verified {DESTINATION}")


if __name__ == "__main__":
    main()

