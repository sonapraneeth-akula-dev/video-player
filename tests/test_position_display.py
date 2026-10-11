from scripts.make_test_media import generate_vfr
from vplayer.settings import Settings
from vplayer.ui.main_window import MainWindow


def test_position_formats_milliseconds_frame_number_and_unknown_fps(qtbot, tmp_path, monkeypatch):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.show()
    try:
        assert MainWindow._clock(0) == "00:00:00.000"
        assert MainWindow._clock(3661.9996) == "01:01:02.000"
        assert MainWindow._clock(float("nan")) == "—"
        monkeypatch.setattr(window.player, "_fps_values", lambda: (25.0, 25.0))
        window._duration_changed(3661.25)
        window._position_changed(1.2)
        assert window.time_label.text() == "00:00:01.200 / 01:01:01.250 · f30"
        window.player.variable_frame_rate = True
        window.player.vfr_detected.emit()
        assert window.time_label.text().endswith("≈ f 30")
        monkeypatch.setattr(window.player, "_fps_values", lambda: (None, None))
        window._position_changed(0)
        assert window.time_label.text().endswith("f —")
        action = next(action for action in window.view_menu.actions() if action.objectName() == "toggle_overlay")
        assert action.shortcut().toString() == "I"
        assert window.time_label.isVisible()
        action.trigger()
        assert not window.time_label.isVisible()
        action.trigger()
        assert window.time_label.isVisible()
    finally:
        window.close()


def test_vfr_clip_shows_approximate_frame_label(qtbot, tmp_path):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.player.mpv.ao = "null"
    window.show()
    try:
        with qtbot.waitSignal(window.player.vfr_detected, timeout=10000):
            window.open_file(generate_vfr(tmp_path))
        assert "≈ f " in window.time_label.text()
        assert window.time_label.text().startswith("00:00:01.")
    finally:
        window.close()
