import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import paramiko
import pytest

if sys.platform == "win32":
    vendor = Path(__file__).resolve().parents[1] / "vendor"
    os.environ["PATH"] = str(vendor) + os.pathsep + os.environ["PATH"]


@pytest.fixture(scope="session")
def sftp_server(tmp_path_factory):
    if not shutil.which("docker"):
        pytest.skip("Docker is required for SFTP integration tests")

    def docker(*arguments):
        result = subprocess.run(["docker", *arguments], text=True, capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError(f"docker {arguments[0]} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    if subprocess.run(["docker", "info"], capture_output=True, check=False).returncode:
        pytest.skip("The Docker daemon is unavailable")
    keys = tmp_path_factory.mktemp("sshd-keys")
    password = secrets.token_urlsafe(24)
    (keys / "password").write_text(password, encoding="utf-8")
    for username in ("key", "agent"):
        private = paramiko.RSAKey.generate(2048)
        private.write_private_key_file(
            str(keys / username), password="test-key-passphrase" if username == "key" else None,
        )
        (keys / f"{username}.pub").write_text(
            f"{private.get_name()} {private.get_base64()} {username}\n", encoding="ascii",
        )
    context = Path(__file__).parent / "docker" / "sshd"
    image = docker("build", "--quiet", str(context)).splitlines()[-1]
    media = Path(__file__).parent / "media"
    container = docker(
        "run", "--detach", "--rm", "--name", f"vplayer-sshd-{uuid4().hex[:12]}",
        "--publish", "127.0.0.1::22",
        "--volume", f"{media.resolve()}:/media:ro",
        "--volume", f"{keys.resolve()}:/keys:ro",
        image,
    )
    try:
        port = int(docker("port", container, "22/tcp").rsplit(":", 1)[1])
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5) as channel:
                    if channel.recv(4) == b"SSH-":
                        break
            except OSError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError(f"OpenSSH container failed to start: {docker('logs', container)}")
        yield SimpleNamespace(
            host="127.0.0.1", port=port, container=container, password=password, key=keys / "key",
            agent_key=keys / "agent", passphrase="test-key-passphrase",
        )
    finally:
        docker("rm", "--force", container)
