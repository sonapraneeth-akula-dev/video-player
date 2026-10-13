from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from vplayer.settings import Settings
from vplayer.ui.main_window import MainWindow

MEDIA = Path(__file__).parent / "media" / "tracks_multi.mkv"


def playing_window(qtbot, tmp_path, mode):
    settings = Settings(tmp_path / "settings.ini")
    settings.set_background_tabs(mode)
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.show()
    tab = window._add_player_tab("Video")
    tab.player.mpv.ao = "null"
    tab.player.mpv.pause = True
    with qtbot.waitSignal(tab.player.file_loaded, timeout=10000):
        window.open_file(MEDIA)
    tab.player.mpv.mute = False
    tab.player.mpv.pause = False
    return window, tab


@pytest.mark.parametrize("mode", ("pause", "muted", "play"))
def test_background_mode_on_tab_switch_preserves_user_play_and_mute(qtbot, tmp_path, mode):
    window, first = playing_window(qtbot, tmp_path, mode)
    try:
        second = window._add_player_tab("Other")
        second.player.mpv.ao = "null"
        second.player.mpv.pause = True
        with qtbot.waitSignal(second.player.file_loaded, timeout=10000):
            window.open_file(MEDIA)
        second.player.mpv.mute = True
        assert first.background_mode == mode
        assert first.player.mpv.pause is (mode == "pause")
        assert first.player.mpv.mute is (mode == "muted")
        window.tabs.setCurrentWidget(first)
        assert first.background_mode is None
        assert first.player.mpv.pause is False
        assert first.player.mpv.mute is False
        assert second.player.mpv.pause is True
        window.tabs.setCurrentWidget(second)
        assert second.player.mpv.pause is True
        assert second.player.mpv.mute is True
    finally:
        window.close()


@pytest.mark.parametrize("mode", ("pause", "muted", "play"))
def test_background_mode_on_window_minimize(qtbot, tmp_path, mode):
    if QApplication.platformName().lower().startswith("wayland"):
        pytest.skip("Wayland does not report minimize events")
    window, tab = playing_window(qtbot, tmp_path, mode)
    try:
        window.showMinimized()
        qtbot.waitUntil(window.isMinimized)
        assert tab.background_mode == mode
        assert tab.player.mpv.pause is (mode == "pause")
        assert tab.player.mpv.mute is (mode == "muted")
        window.showNormal()
        qtbot.waitUntil(lambda: not window.isMinimized())
        assert tab.background_mode is None
        assert tab.player.mpv.pause is False
        assert tab.player.mpv.mute is False
    finally:
        window.close()


def test_background_mode_invalid_setting_repairs_to_pause(tmp_path, caplog):
    settings = Settings(tmp_path / "settings.ini")
    settings.store.setValue("playback/background_tabs", "invalid")
    settings.load()
    assert settings.background_tabs == "pause"
    assert settings.store.value("playback/background_tabs") == "pause"
    assert "Invalid playback/background_tabs" in caplog.text
    with pytest.raises(ValueError, match="Background tabs"):
        settings.set_background_tabs("invalid")


def test_previously_paused_tab_stays_paused_after_minimize(qtbot, tmp_path):
    if QApplication.platformName().lower().startswith("wayland"):
        pytest.skip("Wayland does not report minimize events")
    window, tab = playing_window(qtbot, tmp_path, "pause")
    try:
        tab.player.mpv.pause = True
        window.showMinimized()
        qtbot.waitUntil(window.isMinimized)
        window.showNormal()
        qtbot.waitUntil(lambda: not window.isMinimized())
        assert tab.player.mpv.pause is True
    finally:
        window.close()
