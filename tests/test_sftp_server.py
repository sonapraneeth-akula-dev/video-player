import paramiko
import pytest


@pytest.mark.sftp
def test_openssh_fixture_authenticates_and_lists_media(sftp_server):
    with paramiko.SSHClient() as client:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            sftp_server.host,
            port=sftp_server.port,
            username="password",
            password=sftp_server.password,
            allow_agent=False,
            look_for_keys=False,
            timeout=10,
        )
        with client.open_sftp() as sftp:
            assert "h264_25.mp4" in sftp.listdir("/media")


@pytest.mark.sftp
@pytest.mark.parametrize("username", ("key", "agent"))
def test_openssh_fixture_key_accounts_can_authenticate(sftp_server, username):
    private_path = sftp_server.key if username == "key" else sftp_server.agent_key
    private_key = paramiko.RSAKey.from_private_key_file(
        str(private_path),
        password=sftp_server.passphrase if username == "key" else None,
    )
    with paramiko.SSHClient() as client:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            sftp_server.host,
            port=sftp_server.port,
            username=username,
            pkey=private_key,
            allow_agent=False,
            look_for_keys=False,
            timeout=10,
        )
        with client.open_sftp() as sftp:
            assert "h264_25.mp4" in sftp.listdir("/media")
