import math

import pytest
from PySide6.QtCore import QObject, Signal

from vplayer.sync import SyncController, fps_match


class FakeMpv:
    def __init__(self, owner):
        self.owner = owner
        self.time_pos = 5.0
        self.duration = 12.0
        self.pause = True
        self.speed = 1.0
        self.auto_restart = True
        self.seeks = []
        self.eof_reached = False

    def seek(self, position, *, reference, precision):
        assert (reference, precision) == ("absolute", "exact")
        self.seeks.append(position)
        self.time_pos = position
        if self.auto_restart:
            self.owner.playback_restarted.emit()


class FakePlayer(QObject):
    position = Signal(object)
    playback_restarted = Signal()

    def __init__(self):
        super().__init__()
        self.mpv = FakeMpv(self)

    def frame_rate(self):
        return 25.0

    def seek(self, seconds, *, relative=False):
        self.mpv.time_pos = (self.mpv.time_pos if relative else 0) + seconds
        self.playback_restarted.emit()

    def frame_step(self, direction):
        self.mpv.time_pos += direction / 25
        self.position.emit(self.mpv.time_pos)

    def skip_frames(self, frames):
        self.mpv.time_pos += frames / 25
        self.position.emit(self.mpv.time_pos)

    def set_speed(self, speed):
        self.mpv.speed = speed


@pytest.mark.parametrize(("a", "b"), [(29.97, 30000 / 1001), (25, 25), (24, 24.0009)])
def test_matching_frame_rates(a, b):
    assert fps_match(a, b)
    assert fps_match(b, a)


@pytest.mark.parametrize(("a", "b"), [(29.97, 30), (24, 25), (60, 59.94), (24, 24.001)])
def test_mismatched_rates_show_both_values(a, b):
    with pytest.raises(ValueError, match=f"{a:g} fps vs {b:g} fps"):
        fps_match(a, b)


@pytest.mark.parametrize("unknown", [None, 0, -1, True, math.inf, math.nan, "25"])
def test_unknown_rates_refuse_compare(unknown):
    with pytest.raises(ValueError, match="Frame rate unknown"):
        fps_match(unknown, 25)
    with pytest.raises(ValueError, match="Frame rate unknown"):
        fps_match(25, unknown)


@pytest.mark.parametrize("offset", (0, 2 / 25, -2 / 25))
def test_compare_commands_follow_master_at_offset(offset):
    master, follower = FakePlayer(), FakePlayer()
    controller = SyncController(master, follower, offset=offset)
    try:
        controller.set_speed(1.5)
        assert master.mpv.speed == follower.mpv.speed == 1.5
        controller.frame_step(-1)
        assert abs(follower.mpv.time_pos - (master.mpv.time_pos - offset)) < 1e-9
        controller.skip_frames(3)
        assert abs(follower.mpv.time_pos - (master.mpv.time_pos - offset)) < 1e-9
        master.mpv.pause = False
        controller.seek(6.0)
        assert master.mpv.time_pos == 6.0
        assert abs(follower.mpv.time_pos - (6.0 - offset)) < 1e-9
        assert master.mpv.pause is follower.mpv.pause is False
        controller.play_pause()
        assert master.mpv.pause is follower.mpv.pause is True
        controller.play_pause()
        assert master.mpv.pause is follower.mpv.pause is False
    finally:
        controller.close()


def test_compare_invalid_commands_do_not_change_players():
    master, follower = FakePlayer(), FakePlayer()
    with pytest.raises(ValueError, match="offset"):
        SyncController(master, follower, offset=math.nan)
    controller = SyncController(master, follower)
    try:
        for action, arg in ((controller.frame_step, 0), (controller.skip_frames, 0),
                            (controller.seek, math.inf), (controller.set_speed, math.nan)):
            with pytest.raises(ValueError):
                action(arg)
        assert (master.mpv.time_pos, follower.mpv.time_pos) == (5.0, 5.0)
        assert master.mpv.pause is follower.mpv.pause is True
        follower.mpv.duration = None
        with pytest.raises(RuntimeError, match="loaded"):
            controller.play_pause()
        follower.mpv.duration = 12
        master.mpv.time_pos = math.nan
        with pytest.raises(RuntimeError, match="valid positions"):
            controller.play_pause()
    finally:
        controller.close()


def test_sync_queues_new_commands_until_follower_restarts():
    master, follower = FakePlayer(), FakePlayer()
    follower.mpv.auto_restart = False
    controller = SyncController(master, follower)
    try:
        controller.frame_step(1)
        controller.skip_frames(2)
        assert master.mpv.time_pos == 5.04
        assert follower.mpv.time_pos == 5.04
        follower.playback_restarted.emit()
        assert abs(master.mpv.time_pos - 5.12) < 1e-9
        assert follower.mpv.time_pos == master.mpv.time_pos
        follower.playback_restarted.emit()
        assert controller._waiting is None
        master.mpv.time_pos = follower.mpv.time_pos = 0
        controller.frame_step(-1)
        controller.skip_frames(-3)
        assert controller._waiting is None
        assert (master.mpv.time_pos, follower.mpv.time_pos) == (0, 0)
    finally:
        controller.close()


def test_drift_needs_two_samples_and_is_rate_limited(qapp, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("vplayer.sync.time.monotonic", lambda: clock[0])
    master, follower = FakePlayer(), FakePlayer()
    master.mpv.pause = follower.mpv.pause = False
    controller = SyncController(master, follower)
    try:
        follower.mpv.time_pos = 4.91
        controller._check_drift()
        controller._check_drift()
        assert not follower.mpv.seeks
        follower.mpv.time_pos = 4.8
        controller._check_drift()
        assert not follower.mpv.seeks
        controller._check_drift()
        assert follower.mpv.seeks == [5.0]
        assert master.mpv.pause is follower.mpv.pause is False
        follower.mpv.time_pos = 4.8
        controller._check_drift()
        controller._check_drift()
        assert follower.mpv.seeks == [5.0]
        clock[0] += 2
        controller._check_drift()
        assert follower.mpv.seeks == [5.0, 5.0]
    finally:
        controller.close()


def test_drift_threshold_uses_two_frames_for_low_fps(qapp):
    master, follower = FakePlayer(), FakePlayer()
    master.frame_rate = follower.frame_rate = lambda: 10
    master.mpv.pause = follower.mpv.pause = False
    controller = SyncController(master, follower, offset=0.5)
    try:
        follower.mpv.time_pos = 4.35
        controller._check_drift()
        controller._check_drift()
        assert not follower.mpv.seeks
        follower.mpv.time_pos = 4.2
        controller._check_drift()
        controller._check_drift()
        assert follower.mpv.seeks == [4.5]
        follower.mpv.time_pos = 0
        master.mpv.time_pos = 0
        controller._check_drift()
        controller._check_drift()
        assert follower.mpv.seeks == [4.5, 0]
        assert controller.out_of_range == "B not started yet"
        assert follower.mpv.pause is True
    finally:
        controller.close()


@pytest.mark.parametrize(("offset", "position", "status", "end"), [
    (3.0, 1.0, "B not started yet", 0),
    (-3.0, 11.0, "B ended", 299 / 25),
])
def test_follower_holds_at_nearest_end_and_rejoins(qapp, offset, position, status, end):
    master, follower = FakePlayer(), FakePlayer()
    master.mpv.time_pos = position
    master.mpv.pause = follower.mpv.pause = False
    controller = SyncController(master, follower, offset=offset)
    changes = []
    controller.out_of_range_changed.connect(changes.append)
    try:
        controller._check_drift()
        assert changes == [status]
        assert follower.mpv.pause is True
        assert follower.mpv.seeks == [end]
        controller._check_drift()
        assert follower.mpv.seeks == [end]
        master.mpv.time_pos = 5
        controller._check_drift()
        assert changes == [status, None]
        assert follower.mpv.seeks[-1] == 5 - offset
        assert follower.mpv.pause is False
    finally:
        controller.close()


def test_master_eof_pauses_follower_and_does_not_restart(qapp):
    master, follower = FakePlayer(), FakePlayer()
    master.mpv.pause = follower.mpv.pause = False
    controller = SyncController(master, follower)
    try:
        master.mpv.eof_reached = True
        controller._check_drift()
        assert follower.mpv.pause is True
        master.mpv.pause = True
        controller.play_pause()
        assert master.mpv.pause is follower.mpv.pause is True
        assert follower.mpv.seeks == []
    finally:
        controller.close()


def test_eof_during_follower_seek_does_not_resume(qapp):
    master, follower = FakePlayer(), FakePlayer()
    master.mpv.pause = follower.mpv.pause = False
    follower.mpv.auto_restart = False
    controller = SyncController(master, follower)
    try:
        controller.seek(6.0)
        master.mpv.eof_reached = True
        follower.playback_restarted.emit()
        assert master.mpv.pause is follower.mpv.pause is True
    finally:
        controller.close()
