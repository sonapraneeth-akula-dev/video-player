"""Qt-facing facade for one libmpv playback core."""

import logging
import math
from decimal import Decimal
from pathlib import Path

import mpv
from PySide6.QtCore import QObject, Qt, Signal, Slot

log = logging.getLogger(__name__)
OBSERVED_PROPERTIES = ("time-pos", "duration", "pause", "speed", "hwdec-current")


class Player(QObject):
    file_loaded = Signal()
    position = Signal(object)
    duration = Signal(object)
    paused = Signal(object)
    speed_changed = Signal(object)
    hwdec_current = Signal(object)
    error = Signal(str)
    _update = Signal(str, object)

    def __init__(self, parent: QObject | None = None, *, video_output: str = "libmpv"):
        super().__init__(parent)
        self._closed = False
        self._uri = ""
        self._update.connect(self._deliver, Qt.ConnectionType.QueuedConnection)
        self.mpv = mpv.MPV(
            vo=video_output,
            hwdec="auto-safe",
            config=False,
            load_scripts=False,
            ytdl=False,
            input_default_bindings=False,
            input_vo_keyboard=False,
            osc=False,
            keepaspect=True,
            keep_open=True,
            cache="yes",
            cache_on_disk="no",
            demuxer_max_bytes=64 * 1024 * 1024,
            demuxer_max_back_bytes=32 * 1024 * 1024,
            demuxer_donate_buffer="no",
        )
        for name in OBSERVED_PROPERTIES:
            self.mpv.observe_property(name, self._on_property)
        self.mpv.register_event_callback(self._on_event)

    def _on_property(self, name: str, value: object) -> None:
        self._update.emit(name, value)

    def _on_event(self, event: mpv.MpvEvent) -> None:
        if event.event_id.value == mpv.MpvEventID.FILE_LOADED:
            self._update.emit("file-loaded", None)
        elif event.event_id.value == mpv.MpvEventID.END_FILE and event.data.reason == mpv.MpvEventEndFile.ERROR:
            self._update.emit("error", f"Could not play {self._uri}: mpv error {event.data.error}")

    @Slot(str, object)
    def _deliver(self, name: str, value: object) -> None:
        if self._closed:
            return
        if name == "file-loaded":
            self.file_loaded.emit()
        elif name == "time-pos":
            self.position.emit(value)
        elif name == "duration":
            self.duration.emit(value)
        elif name == "pause":
            self.paused.emit(value)
        elif name == "speed":
            self.speed_changed.emit(value)
        elif name == "hwdec-current":
            if value is not None:
                log.info("Decoder: %s", value)
            self.hwdec_current.emit(value)
        elif name == "error":
            self.error.emit(value)

    def load(self, path: str | Path) -> None:
        file = Path(path)
        if not file.is_file():
            self.error.emit(f"File not found: {file}")
            return
        self._uri = str(file.resolve())
        self.mpv.loadfile(self._uri)

    def play_pause(self) -> None:
        self.mpv.pause = not self.mpv.pause

    def adjust_volume(self, amount: int) -> None:
        self.mpv.volume = max(0, min(self.mpv.volume + amount, 100))
        self.mpv.show_text(f"Volume: {self.mpv.volume:.0f}%", 1000)

    def toggle_mute(self) -> None:
        self.mpv.mute = not self.mpv.mute
        self.mpv.show_text("Muted" if self.mpv.mute else f"Volume: {self.mpv.volume:.0f}%", 1000)

    def set_speed(self, speed: float) -> None:
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(speed):
            self.error.emit("Playback speed must be finite")
            return
        self.mpv.speed = max(0.05, min(speed, 8.0))

    def nudge_speed(self, amount: float) -> None:
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount):
            self.error.emit("Speed adjustment must be finite")
            return
        self.set_speed(float(Decimal(str(self.mpv.speed)) + Decimal(str(amount))))

    def seek(self, seconds: float, relative: bool = False) -> None:
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
            self.error.emit("Seek position must be finite")
            return
        duration = self.mpv.duration
        if duration is None:
            self.error.emit("Cannot seek before a file is loaded")
            return
        fps = self.mpv.container_fps or self.mpv.estimated_vf_fps
        last_frame = max(0.0, duration - (1.0 / fps if fps else 1e-6))
        target = seconds + (self.mpv.time_pos or 0.0) if relative else seconds
        target = max(0.0, min(target, last_frame))
        self.mpv.seek(target, reference="absolute", precision="exact" if target == last_frame else "keyframes")

    def state(self) -> dict[str, object]:
        return {
            "pause": self.mpv.pause,
            "time-pos": self.mpv.time_pos,
            "duration": self.mpv.duration,
            "hwdec-current": self.mpv.hwdec_current,
        }

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            for name in OBSERVED_PROPERTIES:
                self.mpv.unobserve_property(name, self._on_property)
            self.mpv.unregister_event_callback(self._on_event)
            # ponytail: local-only shutdown is synchronous; use a worker when remote streams can block it.
            self.mpv.terminate()
