"""Main window for local playback."""

import math
from pathlib import Path

import mpv
import shiboken6
from PySide6.QtCore import QEvent, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QFocusFrame,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from vplayer import APP_NAME
from vplayer.mpv_widget import MpvWidget
from vplayer.player import Player
from vplayer.settings import Settings
from vplayer.ui.browser import BrowserDock
from vplayer.ui.dialogs import PreferencesDialog


class SeekBar(QSlider):
    seek_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(0, 1_000_000)
        self.setEnabled(False)
        self.setAccessibleName("Seek")

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
        player.file_loaded.connect(lambda: self.play_action.setEnabled(True))
        player.paused.connect(lambda paused: self.play_action.setText("Play" if paused else "Pause"))


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(960, 600)
        self.settings = settings or Settings()
        self.settings.load()
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
        self.video.installEventFilter(self)
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
        open_action = QAction("&Open...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.choose_file)
        self.file_menu = self.menuBar().addMenu("&File")
        self.file_menu.addAction(open_action)
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
        self.player.position.connect(self._position_changed)
        self.player.vfr_detected.connect(self._update_time)
        self.seek_bar.seek_requested.connect(self._seek_from_bar)

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

    def _position_changed(self, position):
        self._position = position or 0.0
        if self._duration and not self.seek_bar.isSliderDown():
            self.seek_bar.setValue(round(self._position / self._duration * self.seek_bar.maximum()))
        self._update_time()

    def _seek_from_bar(self, value):
        if self._duration:
            self.player.seek(value / self.seek_bar.maximum() * self._duration)

    def eventFilter(self, watched, event):
        if watched is self.video:
            if event.type() == QEvent.Type.FocusIn:
                self.video_focus.setWidget(self.video)
                self.video_focus.show()
            elif event.type() == QEvent.Type.FocusOut:
                self.video_focus.setWidget(None)
                self.video_focus.hide()
        return super().eventFilter(watched, event)

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
        dialog = PreferencesDialog(self.settings.pitch_correction, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.accepted.connect(lambda: self._save_pitch_preference(dialog.pitch_correction.isChecked()))
        dialog.open()

    def _save_pitch_preference(self, enabled: bool):
        try:
            self.player.mpv.audio_pitch_correction = enabled
            self.settings.set_pitch_correction(enabled)
        except (OSError, RuntimeError, SystemError, mpv.PropertyUnavailableError) as error:
            self.show_error(f"Could not save pitch correction: {error}")

    def open_file(self, path: str | Path):
        self.banner.hide()
        self.player.load(path)

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
        if shiboken6.isValid(self.video):
            self.video.dispose()
        self.player.close()
        super().closeEvent(event)
