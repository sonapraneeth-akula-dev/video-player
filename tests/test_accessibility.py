from pathlib import Path

import paramiko
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from vplayer.settings import Settings
from vplayer.sftp import KnownHosts
from vplayer.ui.dialogs import ConnectDialog, HostKeyDialog, PreferencesDialog
from vplayer.ui.main_window import MainWindow


def test_visible_keyboard_controls_have_accessible_names(qtbot, tmp_path: Path):
    settings = Settings(tmp_path / "settings.ini")
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.show()
    # Keep a late no-media duration update from disabling the synthetic seek control.
    window.player.duration.disconnect(window._duration_changed)
    window.seek_bar.setEnabled(True)
    window.controls.play_action.setEnabled(True)
    preferences = PreferencesDialog(True, window)
    connect = ConnectDialog(settings=settings, parent=window)
    host_key = HostKeyDialog(
        KnownHosts(tmp_path / "known_hosts", tmp_path / "app_hosts"),
        "host.example", 22, paramiko.RSAKey.generate(1024), lambda: None, window,
    )
    try:
        for dialog in (preferences, connect, host_key):
            dialog.show()
        qtbot.waitUntil(lambda: all(dialog.isVisible() for dialog in (preferences, connect, host_key)))
        unnamed = [
            type(widget).__name__
            for widget in window.findChildren(QWidget)
            if widget.isVisible()
            and widget.isEnabled()
            and widget.focusPolicy() & Qt.FocusPolicy.TabFocus
            and not widget.accessibleName().strip()
        ]
        assert not unnamed
    finally:
        for dialog in (host_key, connect, preferences):
            dialog.close()
        window.close()


def test_keyboard_tab_order_and_focus_feedback(qtbot, tmp_path: Path):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.show()
    try:
        window.activateWindow()
        qtbot.waitUntil(window.isActiveWindow)
        window.video.setFocus()
        qtbot.waitUntil(window.video.hasFocus)
        window.player.duration.disconnect(window._duration_changed)
        window.seek_bar.setEnabled(True)
        window.controls.play_action.setEnabled(True)
        assert window.video_focus.isVisible()
        for expected in (
            window.seek_bar, window.controls.play_button, window.browser.all_files,
            window.browser.tree, window.video,
        ):
            QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Tab)
            qtbot.wait(20)
            assert expected.hasFocus(), f"Expected {type(expected).__name__}, got {type(QApplication.focusWidget()).__name__}"
            if expected is window.controls.play_button:
                assert not window.video_focus.isVisible()
        preferences = PreferencesDialog(True, window)
        preferences.show()
        preferences.activateWindow()
        qtbot.waitUntil(preferences.isActiveWindow)
        preferences.pitch_correction.setFocus()
        QTest.keyClick(preferences.pitch_correction, Qt.Key.Key_Space)
        assert not preferences.pitch_correction.isChecked()
        QTest.keyClick(preferences.pitch_correction, Qt.Key.Key_Tab)
        assert QApplication.focusWidget().accessibleName() == "OK"
        preferences.close()
    finally:
        window.close()


def test_connection_and_host_key_dialogs_operate_from_keyboard(qtbot, tmp_path: Path):
    settings = Settings(tmp_path / "settings.ini")
    connect = ConnectDialog(settings=settings)
    qtbot.addWidget(connect)
    connect.show()
    connect.activateWindow()
    qtbot.waitUntil(connect.isActiveWindow)
    connect.profiles.setFocus()
    QTest.keyClick(connect.profiles, Qt.Key.Key_Tab)
    assert connect.host.hasFocus()
    QTest.keyClick(connect.host, Qt.Key.Key_Tab)
    assert QApplication.focusWidget() in (connect.port, connect.port.lineEdit())
    connect.close()

    host_key = HostKeyDialog(
        KnownHosts(tmp_path / "known_hosts", tmp_path / "app_hosts"),
        "host.example", 22, paramiko.RSAKey.generate(1024), lambda: None,
    )
    qtbot.addWidget(host_key)
    host_key.show()
    host_key.activateWindow()
    qtbot.waitUntil(host_key.isActiveWindow)
    host_key.reject_button.setFocus()
    QTest.keyClick(host_key.reject_button, Qt.Key.Key_Tab)
    assert host_key.accept_once.hasFocus()
    with qtbot.waitSignal(host_key.accepted):
        QTest.keyClick(host_key.accept_once, Qt.Key.Key_Space)
