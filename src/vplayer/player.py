"""Qt-facing facade for one libmpv playback core."""

import ctypes
import itertools
import logging
import math
import posixpath
import re
import threading
import uuid
from decimal import Decimal
from pathlib import Path

import mpv
import paramiko
from PySide6.QtCore import QObject, QStandardPaths, Qt, QTimer, Signal, Slot

from vplayer.sftp import SftpStream

log = logging.getLogger(__name__)
OBSERVED_PROPERTIES = ("time-pos", "duration", "pause", "speed", "hwdec-current")
PROBE_TITLE = "vplayer-software-probe"


def snapshot_name(source: str, time_s: float, fps: float | None = None, collision: int = 1) -> str:
    if not isinstance(source, str) or not source:
        raise ValueError("Snapshot source must be a nonempty path")
    if isinstance(time_s, bool) or not isinstance(time_s, (int, float)) or not math.isfinite(time_s):
        raise ValueError("Snapshot time must be finite")
    if fps is not None and (
        isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(fps) or fps <= 0
    ):
        raise ValueError("Snapshot frame rate must be positive and finite")
    if isinstance(collision, bool) or not isinstance(collision, int) or collision < 1:
        raise ValueError("Snapshot collision index must be positive")

    millis_total = max(0, round(time_s * 1000))
    seconds, millis = divmod(millis_total, 1000)
    hours, remainder = divmod(seconds, 3600)
    minutes, second = divmod(remainder, 60)
    stem = Path(source.replace("\\", "/").rsplit("/", 1)[-1]).stem
    safe_stem = re.sub(r"[^\w.-]", "_", stem).strip(".") or "snapshot"
    suffix = f"_{hours:02}-{minutes:02}-{second:02}.{millis:03}"
    if fps is not None:
        suffix += f"_f{round(millis_total / 1000 * fps)}"
    if collision > 1:
        suffix += f"_{collision}"
    suffix += ".png"
    if len(suffix) >= 120:
        raise ValueError("Snapshot metadata exceeds the filename limit")
    return f"{safe_stem[:120 - len(suffix)].rstrip('.') or 'snapshot'}{suffix}"


class Player(QObject):
    file_loaded = Signal()
    position = Signal(object)
    duration = Signal(object)
    paused = Signal(object)
    speed_changed = Signal(object)
    loop_points_changed = Signal(object, object)
    hwdec_current = Signal(object)
    vfr_detected = Signal()
    skip_status = Signal(str)
    error = Signal(str)
    sftp_open_failed = Signal(str)
    _update = Signal(str, object)

    def __init__(
        self, parent: QObject | None = None, *, video_output: str = "libmpv",
        readahead_mb: int = 64, backbuffer_mb: int = 256, retry_max: int = 6,
        snapshot_dir: Path | None = None, jpeg_quality: int = 90,
    ):
        super().__init__(parent)
        if (
            isinstance(readahead_mb, bool) or not isinstance(readahead_mb, int) or not 16 <= readahead_mb <= 64
            or isinstance(backbuffer_mb, bool) or not isinstance(backbuffer_mb, int) or not 0 <= backbuffer_mb <= 256
        ):
            raise ValueError("Invalid SFTP buffer limits")
        if isinstance(retry_max, bool) or not isinstance(retry_max, int) or not 0 <= retry_max <= 20:
            raise ValueError("SFTP retry count must be between 0 and 20")
        if type(jpeg_quality) is not int or not 50 <= jpeg_quality <= 100:
            raise ValueError("JPEG quality must be between 50 and 100")
        self._closed = False
        self._close_lock = threading.Lock()
        self._loaded_pending = False
        self._uri = ""
        self._start_position: float | None = None
        self._pending_frame_steps: list[int] = []
        self._pending_skip: int | None = None
        self._skip_total = 0
        self._skip_done = 0
        self._skip_direction = 1
        self._skip_waiting_for_pause = False
        self._skip_start: float | None = None
        self._skip_restarted = False
        self._skip_timer = QTimer(self)
        self._skip_timer.setSingleShot(True)
        self._skip_timer.timeout.connect(self._skip_timeout)
        self.variable_frame_rate = False
        self._vfr_checked = False
        self.readahead_mb = readahead_mb
        self.backbuffer_mb = backbuffer_mb
        self.retry_max = retry_max
        self.snapshot_dir = snapshot_dir or Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation),
        ) / "vplayer"
        self.jpeg_quality = jpeg_quality
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
        try:
            self._update.emit(name, value)
        except Exception as error:  # noqa: BLE001 - exceptions must not escape libmpv callbacks
            self._report_callback_error("property", error)

    def _on_event(self, event: mpv.MpvEvent) -> None:
        try:
            self._handle_event(event)
        except Exception as error:  # noqa: BLE001 - exceptions must not escape libmpv callbacks
            self._report_callback_error("event", error)

    def _report_callback_error(self, source: str, error: Exception) -> None:
        log.exception("Unexpected mpv %s callback failure", source)
        with self._close_lock:
            if self._closed:
                return
            try:
                self._update.emit("error", f"Playback error: {error}")
            except (RuntimeError, SystemError):
                log.exception("Could not deliver mpv %s callback error", source)

    def _handle_event(self, event: mpv.MpvEvent) -> None:
        if event.event_id.value == mpv.MpvEventID.FILE_LOADED:
            with self._close_lock:
                if self._closed:
                    return
                if self.mpv.__getitem__("force-media-title", file_local=True) == PROBE_TITLE:
                    # Software probe finished: reload for real, with hwdec only if software could open the video.
                    options = {"hwdec": "auto-safe" if self.mpv.video_codec else "no"}
                    if self._start_position is not None:
                        options["start"] = str(self._start_position)
                    self.mpv.loadfile(self.mpv.path, **options)
                    return
            # A hwdec attempt can fail mid-stream and fall back; announce the file once decoding has settled.
            self._loaded_pending = True
        elif event.event_id.value == mpv.MpvEventID.PLAYBACK_RESTART:
            if self._loaded_pending:
                self._loaded_pending = False
                self._update.emit("file-loaded", None)
            self._update.emit("playback-restart", None)
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
            self._skip_step_changed(value)
            if not self._vfr_checked and isinstance(value, (int, float)) and value >= 1:
                container, estimated = self._fps_values()
                if (
                    isinstance(container, (int, float)) and math.isfinite(container) and container > 0
                    and isinstance(estimated, (int, float)) and math.isfinite(estimated) and estimated > 0
                ):
                    self._vfr_checked = True
                    if abs(estimated / container - 1) > 0.01:
                        self.variable_frame_rate = True
                        self.vfr_detected.emit()
        elif name == "duration":
            self.duration.emit(value)
        elif name == "pause":
            self.paused.emit(value)
            if value and self._skip_waiting_for_pause:
                self._skip_waiting_for_pause = False
                self._skip_next()
            if value and self._pending_skip is not None:
                frames = self._pending_skip
                self._pending_skip = None
                self._skip_frames_paused(frames)
            if value and self._pending_frame_steps:
                steps = self._pending_frame_steps
                self._pending_frame_steps = []
                for direction in steps:
                    self.mpv.command("frame-step" if direction == 1 else "frame-back-step")
        elif name == "speed":
            self.speed_changed.emit(value)
        elif name == "playback-restart":
            self._skip_restarted = True
            self._skip_step_changed(self.mpv.time_pos)
        elif name == "hwdec-current":
            if value is not None:
                log.info("Decoder: %s", value)
            self.hwdec_current.emit(value)
        elif name == "error":
            self.error.emit(value)
        elif name == "sftp-open-failed":
            self.sftp_open_failed.emit(value)

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
            stream = SftpStream(client.open(path, "rb"), retry_max=self.retry_max)
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
            self._update.emit("sftp-open-failed", uri.decode("utf-8", errors="replace"))
            self._update.emit("error", f"Could not open remote file: {error}")
            return mpv.ErrorCode.LOADING_FAILED

    def _sftp_read(self, cookie, buffer, count) -> int:
        stream = None
        try:
            stream = self._sftp_streams[cookie][0]
            data = stream.read(count)
            ctypes.memmove(buffer, data, len(data))
            return len(data)
        except Exception as error:
            if stream is not None and stream.cancelled:
                log.debug("Interrupted cancelled SFTP read: %s", error)
                return -1
            log.exception("Could not read SFTP stream")
            self._update.emit("error", f"Could not read remote file: {error}")
            return -1

    def _sftp_seek(self, cookie, offset) -> int:
        stream = None
        try:
            stream = self._sftp_streams[cookie][0]
            return stream.seek(offset)
        except Exception as error:
            if stream is not None and stream.cancelled:
                log.debug("Interrupted cancelled SFTP seek: %s", error)
                return mpv.ErrorCode.GENERIC
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
        entry = self._sftp_streams.get(cookie)
        if entry is None:
            log.debug("SFTP cancel after close: %s", cookie)
            return
        stream = entry[0]
        try:
            stream.cancel()
        except Exception as error:
            if stream.cancelled:
                log.warning("SFTP close interrupted during cancellation: %s", error)
                return
            log.exception("Could not cancel SFTP stream")
            self._update.emit("error", f"Could not cancel remote file: {error}")

    def _fps_values(self) -> tuple[float | None, float | None]:
        return self.mpv.container_fps, self.mpv.estimated_vf_fps

    def frame_rate(self) -> float | None:
        for value in self._fps_values():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
                return value
        return None

    def _stop_skip(self) -> None:
        if self._skip_total:
            self.skip_status.emit(f"Skipped {self._skip_done}/{self._skip_total}")
        self._skip_timer.stop()
        self._skip_total = 0
        self._skip_start = None
        self._skip_waiting_for_pause = False
        self._pending_skip = None

    def _skip_next(self) -> None:
        if not self._skip_total:
            return
        if self._skip_done == self._skip_total:
            self._stop_skip()
            return
        self._skip_start = self.mpv.time_pos or 0.0
        self._skip_restarted = False
        self._skip_timer.start(2000)
        try:
            self.mpv.command("frame-step" if self._skip_direction > 0 else "frame-back-step")
        except SystemError as error:
            self._stop_skip()
            self.error.emit(f"Could not skip frame: {error}")

    def _skip_step_changed(self, value: object) -> None:
        if (
            self._skip_start is None or not isinstance(value, (int, float))
            or not math.isfinite(value) or abs(value - self._skip_start) < 1e-6
            or (self._skip_direction < 0 and not self._skip_restarted)
            or not self.mpv.pause
        ):
            return
        self._skip_timer.stop()
        self._skip_start = None
        self._skip_done += 1
        if self._skip_done == self._skip_total or (self._skip_direction > 0 and self.mpv.eof_reached):
            self._stop_skip()
        else:
            self.skip_status.emit(f"Skipping {self._skip_done}/{self._skip_total}")
            QTimer.singleShot(0, self._skip_next)

    def _skip_timeout(self) -> None:
        self._skip_restarted = True
        self._skip_step_changed(self.mpv.time_pos)
        if self._skip_start is not None:
            self._stop_skip()

    def load(
        self, path: str | Path, *, transport: paramiko.Transport | None = None,
        start_position: float | None = None,
    ) -> None:
        if start_position is not None and (
            isinstance(start_position, bool)
            or not isinstance(start_position, (float, int))
            or not math.isfinite(start_position)
            or start_position < 0
        ):
            raise ValueError("Start position must be a nonnegative finite number")
        if transport is not None:
            if start_position is not None:
                raise ValueError("Resume position is only supported for local files")
            if not isinstance(transport, paramiko.Transport) or not transport.is_authenticated():
                self.error.emit("An authenticated SSH connection is required")
                return
            if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
                self.error.emit("Remote file path must be an absolute SFTP path")
                return
            self._stop_skip()
            if self._sftp_callbacks is None:
                self._register_sftp()
            self.mpv["demuxer-max-bytes"] = (self.readahead_mb - 10) * 1024 * 1024
            self.mpv["demuxer-max-back-bytes"] = max(0, self.backbuffer_mb - 1) * 1024 * 1024
            self._sftp_sources.clear()
            self._uri = f"vpsftp://{uuid.uuid4().hex}/{posixpath.basename(path)}"
            self._start_position = None
            self._sftp_sources[self._uri] = (transport, path)
            self.variable_frame_rate = False
            self._vfr_checked = False
            self._pending_skip = None
            self.clear_ab_loop()
            self._loadfile()
            return
        file = Path(path)
        if not file.is_file():
            self.error.emit(f"File not found: {file}")
            return
        self._stop_skip()
        self._sftp_sources.clear()
        self.mpv["demuxer-max-bytes"] = 64 * 1024 * 1024
        self.mpv["demuxer-max-back-bytes"] = 32 * 1024 * 1024
        self._uri = str(file.resolve())
        self._start_position = start_position
        self.variable_frame_rate = False
        self._vfr_checked = False
        self._pending_skip = None
        self.clear_ab_loop()
        self._loadfile()

    def _loadfile(self) -> None:
        # libmpv retries forever on the core thread if hwdec and software both fail to open a stream.
        # Null outputs keep the probe off the GUI render thread.
        self.mpv.loadfile(self._uri, hwdec="no", ao="null", vo="null", force_media_title=PROBE_TITLE)

    def set_ab_point(self, point: str) -> None:
        if point not in ("a", "b"):
            raise ValueError("Loop point must be A or B")
        position = self.mpv.time_pos
        duration = self.mpv.duration
        if duration is None or not math.isfinite(duration) or position is None or not math.isfinite(position):
            self.error.emit("Cannot set a loop point before a file is playing")
            return
        setattr(self.mpv, f"ab_loop_{point}", position)
        self.loop_points_changed.emit(self.mpv.ab_loop_a, self.mpv.ab_loop_b)

    def clear_ab_loop(self) -> None:
        self.mpv.ab_loop_a = "no"
        self.mpv.ab_loop_b = "no"
        self.loop_points_changed.emit(self.mpv.ab_loop_a, self.mpv.ab_loop_b)

    def play_pause(self) -> None:
        self._stop_skip()
        self.mpv.pause = not self.mpv.pause

    def adjust_volume(self, amount: int) -> None:
        self._stop_skip()
        self.mpv.volume = max(0, min(self.mpv.volume + amount, 100))
        self.mpv.show_text(f"Volume: {self.mpv.volume:.0f}%", 1000)

    def toggle_mute(self) -> None:
        self._stop_skip()
        self.mpv.mute = not self.mpv.mute
        self.mpv.show_text("Muted" if self.mpv.mute else f"Volume: {self.mpv.volume:.0f}%", 1000)

    def set_speed(self, speed: float) -> None:
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(speed):
            self.error.emit("Playback speed must be finite")
            return
        self._stop_skip()
        self.mpv.speed = max(0.05, min(speed, 8.0))

    def nudge_speed(self, amount: float) -> None:
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount):
            self.error.emit("Speed adjustment must be finite")
            return
        self.set_speed(float(Decimal(str(self.mpv.speed)) + Decimal(str(amount))))

    def frame_step(self, direction: int = 1) -> None:
        if type(direction) is not int or direction not in (-1, 1):
            raise ValueError("Frame step direction must be -1 or 1")
        self._stop_skip()
        if self.mpv.pause:
            self.mpv.command("frame-step" if direction == 1 else "frame-back-step")
        else:
            self._pending_frame_steps.append(direction)
            self.mpv.pause = True

    def _skip_frames_paused(self, frames: int) -> None:
        fps = self.frame_rate()
        duration = self.mpv.duration
        if fps is None or duration is None:
            self.error.emit("Cannot skip frames without a known frame rate and duration")
            return
        last = max(0, math.ceil(duration * fps) - 1)
        current = round((self.mpv.time_pos or 0) * fps)
        target = max(0, min(current + frames, last))
        self.mpv.seek(target / fps, reference="absolute", precision="exact")

    def skip_frames(self, frames: int) -> None:
        if type(frames) is not int or frames == 0 or abs(frames) > 1000:
            raise ValueError("Frame skip must be between -1000 and 1000, excluding zero")
        self._stop_skip()
        if self.mpv.duration is None:
            self.error.emit("Cannot skip frames before a file is loaded")
            return
        self._pending_frame_steps.clear()
        if self.variable_frame_rate or self.frame_rate() is None:
            self._skip_total = abs(frames)
            self._skip_done = 0
            self._skip_direction = 1 if frames > 0 else -1
            self.skip_status.emit(f"Skipping 0/{self._skip_total}")
            if self.mpv.pause:
                self._skip_next()
            else:
                self._skip_waiting_for_pause = True
                self.mpv.pause = True
            return
        if self.mpv.pause:
            self._skip_frames_paused(frames)
        else:
            self._pending_skip = frames
            self.mpv.pause = True

    def seek(self, seconds: float, relative: bool = False) -> None:
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
            self.error.emit("Seek position must be finite")
            return
        duration = self.mpv.duration
        if duration is None:
            self.error.emit("Cannot seek before a file is loaded")
            return
        self._stop_skip()
        fps = self.frame_rate()
        last_frame = max(0.0, duration - (1.0 / fps if fps else 1e-6))
        target = seconds + (self.mpv.time_pos or 0.0) if relative else seconds
        target = max(0.0, min(target, last_frame))
        self.mpv.seek(target, reference="absolute", precision="exact" if target == last_frame else "keyframes")

    def snapshot(self, path: str | Path | None = None) -> Path:
        if self.mpv.duration is None or not self._uri:
            raise ValueError("Cannot take a snapshot before a file is loaded")
        self._stop_skip()
        if path is None:
            self.snapshot_dir.mkdir(parents=True, exist_ok=True)
            candidates = (
                self.snapshot_dir / snapshot_name(self._uri, self.mpv.time_pos or 0, self.frame_rate(), index)
                for index in itertools.count(1)
            )
        else:
            target = Path(path)
            if target.suffix.lower() not in (".png", ".jpg", ".jpeg"):
                raise ValueError("Snapshot file must have a PNG or JPEG extension")
            candidates = iter((target,))
        for target in candidates:
            try:
                with target.open("x"):
                    pass
                break
            except FileExistsError:
                if path is not None:
                    raise
        try:
            if target.suffix.lower() in (".jpg", ".jpeg"):
                self.mpv["screenshot-jpeg-quality"] = self.jpeg_quality
            self.mpv.command("screenshot-to-file", str(target), "video")
        except Exception:
            try:
                if target.exists() and target.stat().st_size == 0:
                    target.unlink()
            except OSError:
                log.exception("Could not remove empty snapshot reservation %s", target)
            raise
        return target

    def state(self) -> dict[str, object]:
        return {
            "pause": self.mpv.pause,
            "time-pos": self.mpv.time_pos,
            "duration": self.mpv.duration,
            "hwdec-current": self.mpv.hwdec_current,
        }

    def close(self) -> None:
        if not self._closed:
            self._stop_skip()
            # The event thread reloads the probe; terminate() must not free the handle under it.
            with self._close_lock:
                self._closed = True
            for name in OBSERVED_PROPERTIES:
                self.mpv.unobserve_property(name, self._on_property)
            self.mpv.unregister_event_callback(self._on_event)
            # ponytail: remote shutdown may block the GUI while an SFTP read is in flight.
            self.mpv.terminate()
            self._sftp_sources.clear()
            self._sftp_callbacks = None
