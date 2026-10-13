from pathlib import Path
from time import perf_counter

import shiboken6
from PySide6.QtWidgets import QPushButton

from vplayer.player import Player
from vplayer.settings import Settings
from vplayer.ui.main_window import MainWindow
from vplayer.ui.tabs import DetachableTabWidget, PlayerTab

MEDIA = Path(__file__).parent / "media" / "tracks_multi.mkv"


def test_tabs_own_independent_playback_and_show_placeholder_when_empty(qtbot):
    tabs = DetachableTabWidget()
    tabs.resize(640, 400)
    tabs.show()
    players = [Player(), Player()]
    try:
        for player in players:
            player.mpv.ao = "null"
        assert tabs.count() == 0
        assert tabs.placeholder.isVisible()
        assert tabs.close_tab(0) is None
        for index, player in enumerate(players):
            tab = PlayerTab(player)
            tabs.new_tab(tab, f"Clip {index + 1}")
            qtbot.waitUntil(lambda tab=tab: tab.video._render is not None, timeout=10000)
            player.mpv.pause = True
            with qtbot.waitSignal(player.file_loaded, timeout=10000):
                player.load(MEDIA)
        first, second = players
        first.set_speed(1.5)
        second.set_speed(0.5)
        first.mpv.volume = 25
        second.mpv.volume = 80
        first.mpv.aid = 1
        second.mpv.aid = 2
        first.seek(0.25)
        qtbot.waitUntil(lambda: (first.mpv.time_pos or 0) >= 0.2, timeout=10000)
        assert first.mpv.speed == 1.5 and second.mpv.speed == 0.5
        assert first.mpv.volume == 25 and second.mpv.volume == 80
        assert first.mpv.aid == 1 and second.mpv.aid == 2
        assert (second.mpv.time_pos or 0) < 0.1
        tabs.prev_tab()
        assert tabs.currentWidget().player is first
        tabs.next_tab()
        assert tabs.currentWidget().player is second
        tabs.close_tab(1)
        assert second.wait_closed(10)
        tabs.close_tab(0)
        assert first.wait_closed(10)
        assert tabs.count() == 0
        assert tabs.placeholder.isVisible()
        assert not shiboken6.isValid(players[0]._video_widget())
    finally:
        for index in reversed(range(tabs.count())):
            tabs.close_tab(index)
        for player in players:
            if not player._closed:
                player.close()
            assert player.wait_closed(10)
        tabs.close()


def test_window_starts_empty_switches_independent_tabs_and_returns_to_placeholder(
    qtbot, tmp_path, monkeypatch,
):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.show()
    assert window.tabs.count() == 0
    assert window.tabs.placeholder.isVisible()
    assert not window.speed_actions[1.0].isEnabled()
    try:
        window._add_player_tab("Video")
        window.player.mpv.ao = "null"
        window.open_file(MEDIA)
        first = window.player
        qtbot.waitUntil(lambda: first.mpv.duration is not None, timeout=10000)
        first.mpv.pause = True
        first.set_speed(1.5)
        first.mpv.volume = 25
        first.mpv.aid = 1
        monkeypatch.setattr(
            "vplayer.ui.main_window.QFileDialog.getOpenFileName",
            lambda *_args: (str(MEDIA), ""),
        )
        add_tab = window._add_player_tab

        def add_tab_without_audio_device(name):
            tab = add_tab(name)
            tab.player.mpv.ao = "null"
            return tab

        monkeypatch.setattr(window, "_add_player_tab", add_tab_without_audio_device)
        window.new_tab()
        second = window.player
        qtbot.waitUntil(lambda: second.mpv.duration is not None, timeout=10000)
        second.mpv.pause = True
        second.set_speed(0.5)
        second.mpv.volume = 80
        second.mpv.aid = 2
        assert window.tabs.count() == 2
        first.error.emit("Error in hidden tab")
        assert not window.banner.isVisible()
        window.prev_tab()
        assert window.player is first and window.video is window.tabs.currentWidget().video
        assert window.banner.text() == "Error in hidden tab" and window.banner.isVisible()
        assert first.mpv.speed == 1.5 and first.mpv.volume == 25 and first.mpv.aid == 1
        assert window.speed_label.text() == "1.5×"
        window._refresh_tracks()
        assert next(a for a in window.audio_menu.actions() if a.text() == "Track 1 (eng)").isChecked()
        window.next_tab()
        assert window.player is second and second.mpv.speed == 0.5 and second.mpv.volume == 80
        assert next(a for a in window.audio_menu.actions() if a.text() == "Track 2 (fra)").isChecked()
        second.mpv.pause = False
        started = perf_counter()
        window.close_tab()
        assert perf_counter() - started < 1
        assert second.wait_closed(10)
        qtbot.waitUntil(lambda: not shiboken6.isValid(second), timeout=10000)
        assert window.player is first
        window.close_tab()
        assert first.wait_closed(10)
        qtbot.waitUntil(lambda: not shiboken6.isValid(first), timeout=10000)
        assert window.tabs.count() == 0
        assert window.tabs.placeholder.isVisible()
    finally:
        window.close()


def test_empty_placeholder_opens_file_without_creating_a_blank_tab(qtbot, tmp_path, monkeypatch):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.show()
    open_button = next(
        button for button in window.tabs.placeholder.findChildren(QPushButton)
        if button.text() == "Open file"
    )
    try:
        monkeypatch.setattr(
            "vplayer.ui.main_window.QFileDialog.getOpenFileName",
            lambda *_args: ("", ""),
        )
        open_button.click()
        assert window.tabs.count() == 0
        missing = tmp_path / "missing.mp4"
        window.open_file(missing)
        assert window.tabs.count() == 0 and window.banner.isVisible()
        monkeypatch.setattr(
            "vplayer.ui.main_window.QFileDialog.getOpenFileName",
            lambda *_args: (str(MEDIA), ""),
        )
        open_button.click()
        assert window.tabs.count() == 1
        qtbot.waitUntil(lambda: window.player.mpv.duration is not None, timeout=10000)
        assert not window.banner.isVisible()
    finally:
        window.close()
