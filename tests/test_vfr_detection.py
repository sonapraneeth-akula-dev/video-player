from pathlib import Path

from scripts.make_test_media import generate_vfr
from vplayer.player import Player

MEDIA = Path(__file__).parent / "media"


def test_vfr_mark_sets_after_one_second_and_resets_for_next_file(qtbot, tmp_path, monkeypatch):
    player = Player(video_output="null")
    try:
        vfr = generate_vfr(tmp_path)
        with qtbot.waitSignal(player.vfr_detected, timeout=10000):
            player.load(vfr)
        assert player.variable_frame_rate
        assert player._vfr_checked
        with qtbot.waitSignal(player.error) as signal:
            player.skip_frames(10)
        assert "single-step fallback" in signal.args[0]
        monkeypatch.setattr(player, "_fps_values", lambda: (60.0, 60.0))
        player._deliver("time-pos", 1.5)
        assert player.variable_frame_rate
        monkeypatch.undo()

        with qtbot.waitSignal(player.file_loaded, timeout=10000):
            player.load(MEDIA / "h264_25.mp4")
        assert not player.variable_frame_rate
        qtbot.waitUntil(lambda: player._vfr_checked, timeout=10000)
        assert not player.variable_frame_rate
    finally:
        player.close()


def test_cfr_stays_unmarked_and_unknown_fps_can_be_forced(qtbot, monkeypatch):
    player = Player(video_output="null")
    try:
        monkeypatch.setattr(player, "_fps_values", lambda: (None, None))
        with qtbot.waitSignal(player.file_loaded, timeout=10000):
            player.load(MEDIA / "h264_25.mp4")
        qtbot.waitUntil(lambda: player.state()["time-pos"] >= 1, timeout=10000)
        assert player.frame_rate() is None
        assert not player._vfr_checked
        assert not player.variable_frame_rate
        assert player.frame_rate() is None
    finally:
        player.close()


def test_vfr_check_waits_for_one_second_and_uses_one_percent_threshold(qtbot, monkeypatch):
    player = Player(video_output="null")
    try:
        monkeypatch.setattr(player, "_fps_values", lambda: (25.0, 25.2))
        player._deliver("time-pos", 0.99)
        assert not player._vfr_checked
        player._deliver("time-pos", 1.0)
        assert player._vfr_checked
        assert not player.variable_frame_rate
        assert player.frame_rate() == 25.0
        player._vfr_checked = False
        monkeypatch.setattr(player, "_fps_values", lambda: (25.0, 25.3))
        with qtbot.waitSignal(player.vfr_detected):
            player._deliver("time-pos", 1.1)
        assert player.variable_frame_rate
    finally:
        player.close()
