"""Frame-rate admission and master-driven paired playback."""

import math
from collections import deque

from PySide6.QtCore import QObject


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
        target = max(0.0, min((self.master.mpv.time_pos or 0.0) - self.offset, self.follower.mpv.duration))
        self.follower.mpv.seek(target, reference="absolute", precision="exact")

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
            if self._resume:
                self.master.mpv.pause = False
                self.follower.mpv.pause = False
            if self._queued:
                self._queued.popleft()()

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
        self._queued.clear()
        self.master.position.disconnect(self._master_position)
        self.master.playback_restarted.disconnect(self._master_restarted)
        self.follower.playback_restarted.disconnect(self._follower_restarted)
