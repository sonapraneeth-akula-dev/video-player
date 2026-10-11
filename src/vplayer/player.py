"""Qt-facing facade for one libmpv playback core."""

import ctypes
import logging
import math
import posixpath
import uuid
from decimal import Decimal
from pathlib import Path

import mpv
import paramiko
from PySide6.QtCore import QObject, Qt, Signal, Slot

from vplayer.sftp import SftpStream

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

    def __init__(
        self, parent: QObject | None = None, *, video_output: str = "libmpv",
        readahead_mb: int = 64, backbuffer_mb: int = 256,
    ):
        super().__init__(parent)
        if (
            isinstance(readahead_mb, bool) or not isinstance(readahead_mb, int) or not 16 <= readahead_mb <= 64
            or isinstance(backbuffer_mb, bool) or not isinstance(backbuffer_mb, int) or not 0 <= backbuffer_mb <= 256
        ):
            raise ValueError("Invalid SFTP buffer limits")
        self._closed = False
        self._uri = ""
        self._pending_frame_steps: list[int] = []
        self.readahead_mb = readahead_mb
        self.backbuffer_mb = backbuffer_mb
        self._sftp_sources: dict[str, tuple[paramiko.Transport, str]] = {}
        self._sftp_streams: dict[int, tuple[SftpStream, paramiko.SFTPClient]] = {}
        self._sftp_callbacks = None
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
            if value and self._pending_frame_steps:
                steps = self._pending_frame_steps
                self._pending_frame_steps = []
                for direction in steps:
                    self.mpv.command("frame-step" if direction == 1 else "frame-back-step")
        elif name == "speed":
            self.speed_changed.emit(value)
        elif name == "hwdec-current":
            if value is not None:
                log.info("Decoder: %s", value)
            self.hwdec_current.emit(value)
        elif name == "error":
            self.error.emit(value)

    def _register_sftp(self) -> None:
        callbacks = (
            mpv.StreamOpenFn(self._sftp_open),
            mpv.StreamReadFn(self._sftp_read),
            mpv.StreamSeekFn(self._sftp_seek),
            mpv.StreamSizeFn(self._sftp_size),
            mpv.StreamCloseFn(self._sftp_close),
            mpv.StreamCancelFn(self._sftp_cancel),
        )
        mpv._mpv_stream_cb_add_ro(self.mpv.handle, b"vpsftp", None, callbacks[0])
        self._sftp_callbacks = callbacks

    def _sftp_open(self, _userdata, uri: bytes, info) -> int:
        client = None
        cookie = None
        try:
            transport, path = self._sftp_sources[uri.decode("utf-8")]
            client = paramiko.SFTPClient.from_transport(transport)
            stream = SftpStream(client.open(path, "rb"))
            cookie = id(stream)
            self._sftp_streams[cookie] = (stream, client)
            info.contents.cookie = cookie
            info.contents.read = self._sftp_callbacks[1]
            info.contents.seek = self._sftp_callbacks[2]
            info.contents.size = self._sftp_callbacks[3]
            info.contents.close = self._sftp_callbacks[4]
            info.contents.cancel = self._sftp_callbacks[5]
            return 0
        except Exception as error:
            if cookie is not None:
                self._sftp_streams.pop(cookie, None)
            if client is not None:
                try:
                    client.close()
                except Exception:
                    log.exception("Could not close failed SFTP connection")
            log.exception("Could not open SFTP stream")
            self._update.emit("error", f"Could not open remote file: {error}")
            return mpv.ErrorCode.LOADING_FAILED

    def _sftp_read(self, cookie, buffer, count) -> int:
        try:
            data = self._sftp_streams[cookie][0].read(count)
            ctypes.memmove(buffer, data, len(data))
            return len(data)
        except Exception as error:
            log.exception("Could not read SFTP stream")
            self._update.emit("error", f"Could not read remote file: {error}")
            return -1

    def _sftp_seek(self, cookie, offset) -> int:
        try:
            return self._sftp_streams[cookie][0].seek(offset)
        except Exception as error:
            log.exception("Could not seek SFTP stream")
            self._update.emit("error", f"Could not seek remote file: {error}")
            return mpv.ErrorCode.GENERIC

    def _sftp_size(self, cookie) -> int:
        try:
            return self._sftp_streams[cookie][0].size()
        except Exception as error:
            log.exception("Could not get SFTP stream size")
            self._update.emit("error", f"Could not get remote file size: {error}")
            return mpv.ErrorCode.GENERIC

    def _sftp_close(self, cookie) -> None:
        try:
            stream, client = self._sftp_streams.pop(cookie)
            try:
                stream.close()
            finally:
                client.close()
        except Exception as error:
            log.exception("Could not close SFTP stream")
            self._update.emit("error", f"Could not close remote file: {error}")

    def _sftp_cancel(self, cookie) -> None:
        try:
            self._sftp_streams[cookie][0].cancel()
        except Exception as error:
            log.exception("Could not cancel SFTP stream")
            self._update.emit("error", f"Could not cancel remote file: {error}")

    def load(self, path: str | Path, *, transport: paramiko.Transport | None = None) -> None:
        if transport is not None:
            if not isinstance(transport, paramiko.Transport) or not transport.is_authenticated():
                self.error.emit("An authenticated SSH connection is required")
                return
            if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
                self.error.emit("Remote file path must be an absolute SFTP path")
                return
            if self._sftp_callbacks is None:
                self._register_sftp()
            self.mpv["demuxer-max-bytes"] = (self.readahead_mb - 10) * 1024 * 1024
            self.mpv["demuxer-max-back-bytes"] = max(0, self.backbuffer_mb - 1) * 1024 * 1024
            self._sftp_sources.clear()
            self._uri = f"vpsftp://{uuid.uuid4().hex}/{posixpath.basename(path)}"
            self._sftp_sources[self._uri] = (transport, path)
            self.mpv.loadfile(self._uri)
            return
        file = Path(path)
        if not file.is_file():
            self.error.emit(f"File not found: {file}")
            return
        self._sftp_sources.clear()
        self.mpv["demuxer-max-bytes"] = 64 * 1024 * 1024
        self.mpv["demuxer-max-back-bytes"] = 32 * 1024 * 1024
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

    def frame_step(self, direction: int = 1) -> None:
        if type(direction) is not int or direction not in (-1, 1):
            raise ValueError("Frame step direction must be -1 or 1")
        if self.mpv.pause:
            self.mpv.command("frame-step" if direction == 1 else "frame-back-step")
        else:
            self._pending_frame_steps.append(direction)
            self.mpv.pause = True

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
            # ponytail: remote shutdown may block the GUI while an SFTP read is in flight.
            self.mpv.terminate()
            self._sftp_sources.clear()
            self._sftp_callbacks = None
