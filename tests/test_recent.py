from pathlib import Path
from unittest.mock import Mock

import paramiko
import pytest

from vplayer.settings import Settings
from vplayer.sftp import KnownHosts
from vplayer.ui.main_window import MainWindow

MEDIA = Path(__file__).resolve().parent / "media" / "h264_25.mp4"


def test_recent_menu_reopens_local_media_and_survives_restart(qtbot, tmp_path):
    settings = Settings(tmp_path / "settings.ini")
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.show()
    try:
        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            window.open_file(MEDIA)
        assert settings.recent_items() == [str(MEDIA.resolve())]
        recent = window.recent_menu.actions()[0]
        assert recent.data() == str(MEDIA.resolve())
        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            recent.trigger()
    finally:
        window.close()

    reopened = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(reopened)
    reopened.show()
    try:
        reopened.recent_menu.aboutToShow.emit()
        assert reopened.recent_menu.actions()[0].data() == str(MEDIA.resolve())
    finally:
        reopened.close()


def test_recent_menu_rejects_sftp_uri_with_password(qtbot, tmp_path):
    settings = Settings(tmp_path / "settings.ini")
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.show()
    try:
        window.open_file("sftp://viewer:password@host.example/clip.mp4")
        assert "Passwords" in window.banner.text()
        assert "password" not in window.banner.text()
        assert settings.recent_items() == []
        assert not window.recent_menu.actions()[0].isEnabled()
    finally:
        window.close()


def test_closing_window_cancels_pending_sftp_connection(qtbot, tmp_path):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.show()
    window.open_file("sftp://viewer@host.example/media/clip.mp4")
    dialog = window._connect_dialog
    assert dialog.isVisible()
    dialog._set_connecting(True)
    window.close()
    transport = Mock()
    dialog._connection_succeeded(transport)
    transport.close.assert_called_once_with()
    assert not window._transports


@pytest.mark.sftp
def test_failed_remote_open_does_not_keep_transport_or_recent_item(qtbot, sftp_server, tmp_path, monkeypatch):
    with paramiko.Transport((sftp_server.host, sftp_server.port)) as transport:
        transport.start_client(timeout=10)
        key = transport.get_remote_server_key()
    known = KnownHosts(tmp_path / "missing_user", tmp_path / "app" / "known_hosts")
    known.remember(sftp_server.host, sftp_server.port, key)
    monkeypatch.setattr("vplayer.ui.main_window.KnownHosts", lambda: known)
    settings = Settings(tmp_path / "settings.ini")
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.show()
    try:
        qtbot.waitUntil(lambda: window.video._render is not None, timeout=10000)
        window.open_file(f"sftp://password@{sftp_server.host}:{sftp_server.port}/media/missing.mp4")
        dialog = window._connect_dialog
        dialog.password.setText(sftp_server.password)
        transports = []
        dialog.connected.connect(transports.append)

        def stale_failure(_transport):
            window._remote_open_failed("vpsftp://earlier/file")
            assert window._active_transport.is_active()

        dialog.connected.connect(stale_failure)
        with qtbot.waitSignal(window.player.error, timeout=15000) as failed:
            dialog.accept()
        assert "Could not open remote file:" in failed.args[0]
        qtbot.waitUntil(lambda: window._active_transport is None, timeout=10000)
        assert len(transports) == 1 and not transports[0].is_active()
        assert not window._transports
        assert settings.recent_items() == []
        assert window.isVisible()
    finally:
        window.close()


@pytest.mark.sftp
def test_recent_sftp_uri_connects_plays_and_reopens(qtbot, sftp_server, tmp_path, monkeypatch):
    with paramiko.Transport((sftp_server.host, sftp_server.port)) as transport:
        transport.start_client(timeout=10)
        key = transport.get_remote_server_key()
    known = KnownHosts(tmp_path / "missing_user", tmp_path / "app" / "known_hosts")
    known.remember(sftp_server.host, sftp_server.port, key)
    monkeypatch.setattr("vplayer.ui.main_window.KnownHosts", lambda: known)
    settings = Settings(tmp_path / "settings.ini")
    uri = f"sftp://password@{sftp_server.host}:{sftp_server.port}/media/h264_25.mp4"
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.show()
    try:
        qtbot.waitUntil(lambda: window.video._render is not None, timeout=10000)
        window.open_file(uri)
        dialog = window._connect_dialog
        dialog.password.setText(sftp_server.password)
        with qtbot.waitSignal(window.player.file_loaded, timeout=20000):
            dialog.accept()
        assert window.player.mpv.path.startswith("vpsftp://")
        assert settings.recent_items() == [uri]
        first_transport = window._active_transport

        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            window.open_file(MEDIA)
        assert not first_transport.is_active()
        assert settings.recent_items() == [str(MEDIA.resolve()), uri]

        next(action for action in window.recent_menu.actions() if action.data() == uri).trigger()
        dialog = window._connect_dialog
        dialog.password.setText(sftp_server.password)
        with qtbot.waitSignal(window.player.file_loaded, timeout=20000):
            dialog.accept()
        assert settings.recent_items() == [uri, str(MEDIA.resolve())]
        active_transport = window._active_transport
    finally:
        window.close()
    assert not active_transport.is_active()
