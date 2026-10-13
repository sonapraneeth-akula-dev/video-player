"""Frame-rate admission and master-driven paired playback."""

import math
import time
from collections import deque

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal


def fps_match(a: float | None, b: float | None) -> bool:
    if any(
        isinstance(fps, bool) or not isinstance(fps, (int, float))
        or not math.isfinite(fps) or fps <= 0
        for fps in (a, b)
    ):
        raise ValueError("Frame rate unknown")
    if abs(a - b) >= 0.001:
        raise ValueError(f"Frame rate mismatch: {a:g} fps vs {b:g} fps")
    return True


class SyncController(QObject):
    out_of_range_changed = Signal(object)

    def __init__(self, master, follower, *, offset: float = 0.0, parent=None):
        super().__init__(parent)
        if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not math.isfinite(offset):
            raise ValueError("Compare offset must be finite")
        fps_match(master.frame_rate(), follower.frame_rate())
        self.master = master
        self.follower = follower
        self.offset = float(offset)
        self._waiting = None
        self._resume = False
        self._origin = None
        self._queued = deque()
        self._drift_streak = 0
        self._last_correction = float("-inf")
        self.out_of_range = None
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._check_drift)
        if QCoreApplication.instance() is not None:
            self._timer.start()
        master.position.connect(self._master_position)
        master.playback_restarted.connect(self._master_restarted)
        follower.playback_restarted.connect(self._follower_restarted)

    def _loaded(self):
        for player in (self.master, self.follower):
            duration = player.mpv.duration
            position = player.mpv.time_pos
            if (
                not isinstance(duration, (int, float)) or isinstance(duration, bool)
                or not math.isfinite(duration) or duration <= 0
                or position is not None and (
                    not isinstance(position, (int, float)) or isinstance(position, bool)
                    or not math.isfinite(position) or position < 0
                )
            ):
                raise RuntimeError("Both compare videos must be loaded with valid positions")
        fps_match(self.master.frame_rate(), self.follower.frame_rate())

    def _align(self):
        self._waiting = "follower"
        mapped = (self.master.mpv.time_pos or 0.0) - self.offset
        self._set_range("B not started yet" if mapped < 0 else "B ended" if mapped > self.follower.mpv.duration else None)
        last = max(0, math.ceil(self.follower.mpv.duration * self.follower.frame_rate()) - 1)
        target = max(0.0, min(mapped, last / self.follower.frame_rate()))
        self.follower.mpv.seek(target, reference="absolute", precision="exact")

    def _set_range(self, status):
        if self.out_of_range != status:
            self.out_of_range = status
            self.out_of_range_changed.emit(status)

    def _master_position(self, _position):
        if (
            self._waiting == "position" and self.master.mpv.time_pos is not None
            and self.master.mpv.time_pos != self._origin
        ):
            self._align()

    def _master_restarted(self):
        if self._waiting == "master":
            self._align()

    def _follower_restarted(self):
        if self._waiting == "follower":
            self._waiting = None
            if self._resume and not self.master.mpv.eof_reached:
                self.master.mpv.pause = False
                if self.out_of_range is None:
                    self.follower.mpv.pause = False
            if self._queued:
                self._queued.popleft()()

    def _check_drift(self):
        if self._waiting is not None:
            self._drift_streak = 0
            return
        a_position = self.master.mpv.time_pos
        b_position = self.follower.mpv.time_pos
        duration = self.follower.mpv.duration
        fps = self.master.frame_rate()
        if any(
            not isinstance(value, (int, float)) or not math.isfinite(value)
            for value in (a_position, b_position, duration, fps)
        ) or fps <= 0:
            self._drift_streak = 0
            return
        if self.master.mpv.eof_reached:
            if not self.follower.mpv.pause:
                self.follower.mpv.pause = True
            self._drift_streak = 0
            return
        target = a_position - self.offset
        if not 0 <= target <= duration:
            status = "B not started yet" if target < 0 else "B ended"
            if self.out_of_range != status:
                self._resume = not self.master.mpv.pause
                self.follower.mpv.pause = True
                self._align()
            self._drift_streak = 0
            return
        if self.out_of_range is not None:
            self._resume = not self.master.mpv.pause
            self._align()
            return
        if self.master.mpv.pause or self.follower.mpv.pause:
            self._drift_streak = 0
            return
        threshold = max(2 / fps, 0.1)
        self._drift_streak = self._drift_streak + 1 if abs(a_position - self.offset - b_position) > threshold else 0
        now = time.monotonic()
        if self._drift_streak >= 2 and now - self._last_correction >= 2:
            self._drift_streak = 0
            self._last_correction = now
            self._start("follower")
            self._align()

    def _start(self, event):
        self._loaded()
        if self._waiting is not None:
            raise RuntimeError("Previous compare command has not completed")
        self._resume = not self.master.mpv.pause
        self.master.mpv.pause = True
        self.follower.mpv.pause = True
        self._waiting = event
        self._origin = self.master.mpv.time_pos

    def play_pause(self):
        self._loaded()
        if self._waiting is not None:
            self._queued.append(self.play_pause)
            return
        if self.master.mpv.pause:
            if self.master.mpv.eof_reached:
                return
            self._start("follower")
            self._resume = True
            self._align()
        else:
            self.master.mpv.pause = self.follower.mpv.pause = True

    def seek(self, seconds: float, *, relative: bool = False):
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
            raise ValueError("Compare seek must be finite")
        if self._waiting is not None:
            self._queued.append(lambda: self.seek(seconds, relative=relative))
            return
        self._start("master")
        self.master.seek(seconds, relative=relative)

    def frame_step(self, direction: int = 1):
        if type(direction) is not int or direction not in (-1, 1):
            raise ValueError("Frame step direction must be -1 or 1")
        if self._waiting is not None:
            self._queued.append(lambda: self.frame_step(direction))
            return
        self._loaded()
        fps = self.master.frame_rate()
        position = self.master.mpv.time_pos
        duration = self.master.mpv.duration
        if position is not None:
            current = round(position * fps)
            if max(0, min(current + direction, math.ceil(duration * fps) - 1)) == current:
                return
        self._start("position")
        self._resume = False
        self.master.frame_step(direction)

    def skip_frames(self, frames: int):
        if type(frames) is not int or frames == 0 or abs(frames) > 1000:
            raise ValueError("Frame skip must be between -1000 and 1000, excluding zero")
        if self._waiting is not None:
            self._queued.append(lambda: self.skip_frames(frames))
            return
        self._loaded()
        fps = self.master.frame_rate()
        position = self.master.mpv.time_pos
        duration = self.master.mpv.duration
        if position is not None:
            current = round(position * fps)
            if max(0, min(current + frames, math.ceil(duration * fps) - 1)) == current:
                return
        self._start("position")
        self._resume = False
        self.master.skip_frames(frames)

    def set_speed(self, speed: float):
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(speed):
            raise ValueError("Compare speed must be finite")
        self._loaded()
        self.master.set_speed(speed)
        self.follower.set_speed(self.master.mpv.speed)

    def close(self):
        self._timer.stop()
        self._queued.clear()
        self.master.position.disconnect(self._master_position)
        self.master.playback_restarted.disconnect(self._master_restarted)
        self.follower.playback_restarted.disconnect(self._follower_restarted)
