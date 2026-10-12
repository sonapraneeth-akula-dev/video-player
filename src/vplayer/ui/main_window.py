"""Main window for local and remote playback."""

import math
from pathlib import Path

import mpv
import paramiko
import shiboken6
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFocusFrame,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from vplayer import APP_NAME
from vplayer.mpv_widget import MpvWidget
from vplayer.player import Player
from vplayer.settings import Settings
from vplayer.sftp import KnownHosts, SshPool
from vplayer.ui.browser import BrowserDock
from vplayer.ui.dialogs import ConnectDialog, PreferencesDialog


class SeekBar(QSlider):
    seek_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(0, 1_000_000)
        self.setEnabled(False)
        self.setAccessibleName("Seek")
        self.loop_a = None
        self.loop_b = None
        self.loop_duration = 0.0

    def set_loop_points(self, a, b, duration):
        self.loop_a = a if isinstance(a, (float, int)) and not isinstance(a, bool) and math.isfinite(a) else None
        self.loop_b = b if isinstance(b, (float, int)) and not isinstance(b, bool) and math.isfinite(b) else None
        self.loop_duration = duration if isinstance(duration, (float, int)) and math.isfinite(duration) and duration > 0 else 0
        marks = [f"{label}: {point:.3f}s" for label, point in (("A", self.loop_a), ("B", self.loop_b)) if point is not None]
        self.setAccessibleDescription(", ".join(marks))
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.loop_duration:
            return
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self,
        )
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self,
        )
        span = max(0, groove.width() - handle.width())
        painter = QPainter(self)
        painter.setPen(QPen(self.palette().highlight().color(), 2))
        for point in (self.loop_a, self.loop_b):
            if point is not None:
                value = round(max(0, min(point / self.loop_duration, 1)) * self.maximum())
                x = groove.x() + handle.width() // 2 + QStyle.sliderPositionFromValue(
                    self.minimum(), self.maximum(), value, span, option.upsideDown,
                )
                painter.drawLine(x, 0, x, self.height())

    def _move_to(self, x):
        self.setValue(QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), round(x), self.width()))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self._move_to(event.position().x())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self._move_to(event.position().x())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self._move_to(event.position().x())
            self.setSliderDown(False)
            self.seek_requested.emit(self.value())
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class ControlBar(QToolBar):
    def __init__(self, player: Player, parent=None):
        super().__init__(parent)
        self.setMovable(False)
        self.play_action = QAction("Play", self)
        self.play_action.setShortcut("Space")
        self.play_action.setEnabled(False)
        self.play_action.triggered.connect(player.play_pause)
        self.addAction(self.play_action)
        self.play_button = self.widgetForAction(self.play_action)
        self.play_button.setAccessibleName("Play or pause")
        self.play_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        player.file_loaded.connect(lambda: self.play_action.setEnabled(True))
        player.paused.connect(lambda paused: self.play_action.setText("Play" if paused else "Pause"))


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(960, 600)
        self.settings = settings or Settings()
        self.settings.load()
        self._current_file: Path | None = None
        self._active_transport = None
        self._transports = []
        self._pending_recent: tuple[str, str] | None = None
        self._connect_dialog = None
        self.player = Player(
            self, readahead_mb=self.settings.readahead_mb, backbuffer_mb=self.settings.backbuffer_mb,
            snapshot_dir=self.settings.snapshot_dir, jpeg_quality=self.settings.jpeg_quality,
        )
        if self.player.mpv.audio_pitch_correction != self.settings.pitch_correction:
            self.player.mpv.audio_pitch_correction = self.settings.pitch_correction
        self.speed_label = QLabel("1×", self)
        self.speed_label.setAccessibleName("Playback speed")
        self.statusBar().addPermanentWidget(self.speed_label)
        self.player.speed_changed.connect(lambda speed: self.speed_label.setText(f"{speed:g}×"))
        self.player.file_loaded.connect(self._file_opened)
        self.player.sftp_open_failed.connect(self._remote_open_failed)
        self.player.skip_status.connect(self.statusBar().showMessage)
        self.snapshot_button = QPushButton("Open folder", self)
        self.snapshot_button.setAccessibleName("Open snapshot folder")
        self.snapshot_button.hide()
        self.snapshot_button.clicked.connect(self.open_snapshot_folder)
        self.statusBar().addPermanentWidget(self.snapshot_button)
        self._snapshot_timer = QTimer(self)
        self._snapshot_timer.setSingleShot(True)
        self._snapshot_timer.timeout.connect(self.snapshot_button.hide)
        self._snapshot_folder: Path | None = None

        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        self.banner = QLabel(content)
        self.banner.setAccessibleName("Playback error")
        self.banner.setWordWrap(True)
        self.banner.hide()
        layout.addWidget(self.banner)
        self.video = MpvWidget(self.player, content)
        self.video.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.video.setAccessibleName("Video playback")
        layout.addWidget(self.video, 1)
        self.video_focus = QFocusFrame(content)
        self.video_focus.hide()
        QApplication.instance().focusChanged.connect(self._focus_changed)
        self.seek_bar = SeekBar(content)
        layout.addWidget(self.seek_bar)
        self.time_label = QLabel("00:00:00.000 / 00:00:00.000 · f —", content)
        self.time_label.setAccessibleName("Playback position")
        layout.addWidget(self.time_label)
        self.setCentralWidget(content)

        self.controls = ControlBar(self.player, self)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, self.controls)
        self.browser = BrowserDock(self)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.browser)
        self.browser.file_activated.connect(self.open_file)
        QWidget.setTabOrder(self.browser.all_files, self.browser.tree)
        QWidget.setTabOrder(self.browser.tree, self.video)
        QWidget.setTabOrder(self.video, self.seek_bar)
        QWidget.setTabOrder(self.seek_bar, self.controls.play_button)
        QWidget.setTabOrder(self.controls.play_button, self.browser.all_files)
        open_action = QAction("&Open...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.choose_file)
        self.file_menu = self.menuBar().addMenu("&File")
        self.file_menu.addAction(open_action)
        self.recent_menu = self.file_menu.addMenu("Recent Files")
        self.recent_menu.aboutToShow.connect(self._refresh_recent_menu)
        self._refresh_recent_menu()
        preferences_action = QAction("Preferences...", self)
        preferences_action.triggered.connect(self.show_preferences)
        self.file_menu.addAction(preferences_action)
        snapshot_action = QAction("Snapshot", self)
        snapshot_action.setObjectName("snapshot")
        snapshot_action.setShortcut("S")
        snapshot_action.triggered.connect(self.snapshot)
        self.file_menu.addAction(snapshot_action)
        snapshot_as_action = QAction("Snapshot As...", self)
        snapshot_as_action.setObjectName("snapshot_as")
        snapshot_as_action.setShortcut("Ctrl+Shift+S")
        snapshot_as_action.triggered.connect(self.snapshot_as)
        self.file_menu.addAction(snapshot_as_action)
        self.view_menu = self.menuBar().addMenu("&View")
        browser_action = self.browser.toggleViewAction()
        browser_action.setShortcut("Ctrl+B")
        self.view_menu.addAction(browser_action)
        self.playback_menu = self.menuBar().addMenu("&Playback")
        self.playback_menu.addAction(self.controls.play_action)
        self.audio_menu = self.menuBar().addMenu("&Audio")
        self.subtitle_menu = self.menuBar().addMenu("S&ubtitles")
        self.cycle_audio = QAction("Next audio track", self)
        self.cycle_audio.setShortcut("A")
        self.cycle_audio.triggered.connect(lambda: self._cycle_track("audio", "aid"))
        self.cycle_sub = QAction("Next subtitle track", self)
        self.cycle_sub.setShortcut("J")
        self.cycle_sub.triggered.connect(lambda: self._cycle_track("sub", "sid"))
        self.audio_menu.aboutToShow.connect(self._refresh_tracks)
        self.subtitle_menu.aboutToShow.connect(self._refresh_tracks)
        self.player.file_loaded.connect(self._refresh_tracks)
        self._refresh_tracks()
        overlay_action = QAction("Show position overlay", self)
        overlay_action.setObjectName("toggle_overlay")
        overlay_action.setShortcut("I")
        overlay_action.setCheckable(True)
        overlay_action.setChecked(True)
        overlay_action.toggled.connect(self.time_label.setVisible)
        self.view_menu.addAction(overlay_action)
        self.speed_actions = {}
        for index, speed in enumerate((0.25, 0.5, 0.67, 1.0, 2.0, 4.0), start=1):
            action = QAction(f"{speed:g}× speed", self)
            action.setObjectName(f"speed_{str(speed).replace('.', '_')}")
            action.setShortcut(f"Alt+{index}")
            action.triggered.connect(lambda checked=False, rate=speed: self.player.set_speed(rate))
            self.playback_menu.addAction(action)
            self.speed_actions[speed] = action
        for name, label, key, callback in (
            ("speed_up", "Speed up", "]", lambda: self.player.nudge_speed(self.settings.speed_step)),
            ("speed_down", "Speed down", "[", lambda: self.player.nudge_speed(-self.settings.speed_step)),
            ("speed_reset", "Normal speed", "Backspace", lambda: self.player.set_speed(1.0)),
        ):
            action = QAction(label, self)
            action.setObjectName(name)
            action.setShortcut(key)
            action.triggered.connect(callback)
            self.playback_menu.addAction(action)
        self.frame_next = QAction("Next frame", self)
        self.frame_next.setObjectName("frame_next")
        self.frame_next.setShortcut(".")
        self.frame_next.setEnabled(False)
        self.frame_next.triggered.connect(lambda: self.player.frame_step())
        self.player.file_loaded.connect(lambda: self.frame_next.setEnabled(True))
        self.playback_menu.addAction(self.frame_next)
        self.frame_prev = QAction("Previous frame", self)
        self.frame_prev.setObjectName("frame_prev")
        self.frame_prev.setShortcut(",")
        self.frame_prev.setEnabled(False)
        self.frame_prev.triggered.connect(lambda: self.player.frame_step(-1))
        self.player.file_loaded.connect(lambda: self.frame_prev.setEnabled(True))
        self.playback_menu.addAction(self.frame_prev)
        for name, label, key, direction in (
            ("skip_n_fwd", "Skip frames forward", "Ctrl+.", 1),
            ("skip_n_back", "Skip frames back", "Ctrl+,", -1),
        ):
            action = QAction(label, self)
            action.setObjectName(name)
            action.setShortcut(key)
            action.setEnabled(False)
            action.triggered.connect(
                lambda checked=False, sign=direction: self.player.skip_frames(sign * self.settings.skip_frames),
            )
            self.player.file_loaded.connect(lambda enabled_action=action: enabled_action.setEnabled(True))
            self.playback_menu.addAction(action)
        for label, key, amount in (
            ("Seek forward", "Right", self.settings.seek_short_s),
            ("Seek back", "Left", -self.settings.seek_short_s),
            ("Seek forward 60s", "Shift+Right", self.settings.seek_long_s),
            ("Seek back 60s", "Shift+Left", -self.settings.seek_long_s),
        ):
            action = QAction(label, self)
            action.setShortcut(key)
            action.triggered.connect(lambda checked=False, delta=amount: self.player.seek(delta, relative=True))
            self.playback_menu.addAction(action)
        for label, key, callback in (
            ("Volume up", "Up", lambda: self.player.adjust_volume(5)),
            ("Volume down", "Down", lambda: self.player.adjust_volume(-5)),
            ("Mute", "M", self.player.toggle_mute),
            ("Fullscreen", "F", self.toggle_fullscreen),
            ("Exit fullscreen", "Esc", self.exit_fullscreen),
        ):
            action = QAction(label, self)
            action.setShortcut(key)
            action.triggered.connect(callback)
            self.playback_menu.addAction(action)
        self.player.error.connect(self.show_error)
        self.player.file_loaded.connect(self.banner.hide)
        self._duration = 0.0
        self._position = 0.0
        self.player.duration.connect(self._duration_changed)
        self.player.loop_points_changed.connect(self._update_loop_markers)
        self.player.position.connect(self._position_changed)
        self.player.vfr_detected.connect(self._update_time)
        self.seek_bar.seek_requested.connect(self._seek_from_bar)
        for name, label, shortcut, callback in (
            ("ab_set_a", "Set loop start (A)", "Ctrl+Alt+1", lambda: self.player.set_ab_point("a")),
            ("ab_set_b", "Set loop end (B)", "Ctrl+Alt+2", lambda: self.player.set_ab_point("b")),
            ("ab_clear", "Clear A-B loop", "Ctrl+Alt+0", self.player.clear_ab_loop),
        ):
            action = QAction(label, self)
            action.setObjectName(name)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            self.playback_menu.addAction(action)

    @staticmethod
    def _clock(seconds: float) -> str:
        if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
            return "—"
        whole, millis = divmod(round(seconds * 1000), 1000)
        hours, remainder = divmod(whole, 3600)
        minutes, second = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{second:02}.{millis:03}"

    def _update_time(self):
        fps = self.player.frame_rate()
        frame = "f —" if fps is None else f"f{round(self._position * fps)}"
        if fps is not None and self.player.variable_frame_rate:
            frame = f"≈ f {round(self._position * fps)}"
        self.time_label.setText(f"{self._clock(self._position)} / {self._clock(self._duration)} · {frame}")

    def _duration_changed(self, duration):
        self._duration = duration or 0.0
        self.seek_bar.setEnabled(self._duration > 0)
        self._update_time()
        self._update_loop_markers()

    def _update_loop_markers(self, *_args):
        self.seek_bar.set_loop_points(self.player.mpv.ab_loop_a, self.player.mpv.ab_loop_b, self._duration)

    def _position_changed(self, position):
        self._position = position or 0.0
        if self._duration and not self.seek_bar.isSliderDown():
            self.seek_bar.setValue(round(self._position / self._duration * self.seek_bar.maximum()))
        self._update_time()

    def _seek_from_bar(self, value):
        if self._duration:
            self.player.seek(value / self.seek_bar.maximum() * self._duration)

    def _focus_changed(self, _previous, current):
        if current is self.video:
            self.video_focus.setWidget(self.video)
            self.video_focus.show()
        else:
            self.video_focus.setWidget(None)
            self.video_focus.hide()

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Video")
        if path:
            self.open_file(path)

    def show_preferences(self):
        dialog = self.findChild(PreferencesDialog)
        if dialog is not None and dialog.isVisible():
            dialog.raise_()
            dialog.activateWindow()
            return
        dialog = PreferencesDialog(self.settings.pitch_correction, self, resume_enabled=self.settings.resume_enabled)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.accepted.connect(lambda: self._save_pitch_preference(dialog.pitch_correction.isChecked()))
        dialog.accepted.connect(lambda: self._save_resume_preference(dialog.resume_enabled.isChecked()))
        dialog.open()

    def _save_pitch_preference(self, enabled: bool):
        try:
            self.player.mpv.audio_pitch_correction = enabled
            self.settings.set_pitch_correction(enabled)
        except (OSError, RuntimeError, SystemError, mpv.PropertyUnavailableError) as error:
            self.show_error(f"Could not save pitch correction: {error}")

    def _save_resume_preference(self, enabled: bool):
        try:
            self.settings.set_resume_enabled(enabled)
        except OSError as error:
            self.show_error(f"Could not save resume preference: {error}")

    def _save_position(self):
        if not self.settings.resume_enabled or self._current_file is None:
            return
        if self.player.mpv.path != str(self._current_file):
            return
        position = self.player.mpv.time_pos
        if isinstance(position, (int, float)) and math.isfinite(position) and position >= 0:
            self.settings.set_resume_position(self._current_file, position)

    def open_file(self, path: str | Path):
        self.banner.hide()
        if isinstance(path, str) and path.lower().startswith("sftp://"):
            if self._connect_dialog is not None and self._connect_dialog.isVisible():
                self._connect_dialog.raise_()
                self._connect_dialog.activateWindow()
                return
            try:
                dialog = ConnectDialog.for_sftp_uri(
                    path, settings=self.settings, pool=SshPool(KnownHosts()), parent=self,
                )
            except (OSError, TypeError, ValueError, paramiko.SSHException) as error:
                self.show_error(f"Could not open SFTP file: {error}")
                return
            self._connect_dialog = dialog
            dialog.connected.connect(lambda transport: self._open_remote(path, dialog.remote_path, transport))
            dialog.finished.connect(lambda: setattr(self, "_connect_dialog", None))
            dialog.open()
            return
        file = Path(path)
        if not file.is_file():
            self.player.load(path)
            return
        self._save_position()
        self._current_file = file.resolve()
        self._active_transport = None
        start = self.settings.resume_position(self._current_file) if self.settings.resume_enabled else None
        self.player.load(self._current_file, start_position=start)
        self._pending_recent = (self.player._uri, str(self._current_file))

    def _open_remote(self, uri: str, remote_path: str, transport):
        self._save_position()
        self._current_file = None
        self._active_transport = transport
        self._transports.append(transport)
        self.player.load(remote_path, transport=transport)
        self._pending_recent = (self.player._uri, uri)

    def _file_opened(self):
        for transport in self._transports[:]:
            if transport is not self._active_transport:
                transport.close()
                self._transports.remove(transport)
        if self._pending_recent is not None and self._pending_recent[0] == self.player._uri:
            try:
                self.settings.add_recent_item(self._pending_recent[1])
                self._refresh_recent_menu()
            except OSError as error:
                self.show_error(str(error))
            self._pending_recent = None

    def _remote_open_failed(self, failed_uri: str):
        if (
            self._active_transport is not None
            and self._pending_recent is not None
            and self._pending_recent[0] == failed_uri
        ):
            transport = self._active_transport
            self._active_transport = None
            self._pending_recent = None
            transport.close()
            self._transports.remove(transport)

    def _refresh_recent_menu(self):
        self.recent_menu.clear()
        try:
            items = self.settings.recent_items()
        except OSError as error:
            self.show_error(str(error))
            items = []
        for item in items:
            action = self.recent_menu.addAction(item.replace("&", "&&"))
            action.setData(item)
            action.triggered.connect(lambda checked=False, source=item: self.open_file(source))
        if not items:
            self.recent_menu.addAction("(empty)").setEnabled(False)

    def _refresh_tracks(self):
        tracks = self.player.mpv.track_list
        for menu, kind, prop, cycle in (
            (self.audio_menu, "audio", "aid", self.cycle_audio),
            (self.subtitle_menu, "sub", "sid", self.cycle_sub),
        ):
            menu.clear()
            menu.addAction(cycle)
            menu.addSeparator()
            available = [track for track in tracks if track["type"] == kind]
            cycle.setEnabled(bool(available))
            selected = getattr(self.player.mpv, prop)
            off = menu.addAction("Off")
            off.setEnabled(bool(available))
            off.setCheckable(True)
            off.setChecked(selected is False)
            off.setData("no")
            off.triggered.connect(lambda checked=False, name=prop: self._select_track(name, "no"))
            for track in available:
                track_id = track["id"]
                detail = track.get("title") or track.get("lang")
                label = f"Track {track_id}"
                if detail:
                    label += f" ({''.join(c for c in str(detail) if c.isprintable())[:80].replace('&', '&&')})"
                action = menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(selected == track_id)
                action.setData(track_id)
                action.triggered.connect(
                    lambda checked=False, name=prop, number=track_id: self._select_track(name, number),
                )

    def _select_track(self, prop: str, track_id: int | str):
        try:
            setattr(self.player.mpv, prop, track_id)
        except (ValueError, RuntimeError, SystemError, mpv.PropertyUnavailableError) as error:
            self.show_error(f"Could not select track: {error}")
            return
        selected = getattr(self.player.mpv, prop)
        menu = self.audio_menu if prop == "aid" else self.subtitle_menu
        for action in menu.actions():
            if action.isCheckable():
                action.setChecked(action.data() == ("no" if selected is False else selected))

    def _cycle_track(self, kind: str, prop: str):
        ids = [track["id"] for track in self.player.mpv.track_list if track["type"] == kind]
        if not ids:
            return
        selected = getattr(self.player.mpv, prop)
        next_index = ids.index(selected) + 1 if selected in ids else 0
        self._select_track(prop, ids[next_index] if next_index < len(ids) else "no")

    def snapshot(self):
        self._save_snapshot()

    def snapshot_as(self):
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Save Snapshot As", str(self.settings.snapshot_dir),
            "PNG image (*.png);;JPEG image (*.jpg *.jpeg)",
        )
        if not path:
            return
        if not Path(path).suffix:
            path += ".jpg" if selected_filter.startswith("JPEG") else ".png"
        self._save_snapshot(path)

    def _save_snapshot(self, path: str | None = None):
        try:
            saved = self.player.snapshot(path)
        except (OSError, SystemError, ValueError) as error:
            self.show_error(f"Could not save snapshot: {error}")
            return
        self._snapshot_folder = saved.parent
        self.statusBar().showMessage(f"Saved snapshot: {saved}", 8000)
        self.snapshot_button.show()
        self._snapshot_timer.start(8000)

    def open_snapshot_folder(self):
        if self._snapshot_folder is not None and not QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self._snapshot_folder)),
        ):
            self.show_error(f"Could not open snapshot folder: {self._snapshot_folder}")

    def show_error(self, message: str):
        self.banner.setText(message)
        self.banner.show()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def exit_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()

    def closeEvent(self, event):
        if self._connect_dialog is not None:
            self._connect_dialog.reject()
        self._save_position()
        if shiboken6.isValid(self.video):
            self.video.dispose()
        self.player.close()
        for transport in self._transports:
            transport.close()
        self._transports.clear()
        super().closeEvent(event)
