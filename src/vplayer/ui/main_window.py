"""Main window for local and remote playback."""

import math
import sys
import threading
from pathlib import Path
from typing import ClassVar

import mpv
import paramiko
import shiboken6
from PySide6.QtCore import QEvent, QStringListModel, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCompleter,
    QFileDialog,
    QFocusFrame,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from vplayer import APP_NAME, MEDIA_EXTS
from vplayer.player import Player
from vplayer.settings import Settings
from vplayer.sftp import KnownHosts, SshPool
from vplayer.ui.browser import BrowserDock
from vplayer.ui.dialogs import ConnectDialog, PreferencesDialog
from vplayer.ui.tabs import DetachableTabWidget, PlayerTab

SPEED_OPTIONS = (0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 4.0, 8.0, 16.0)
VIDEO_FILTER = "Video files (" + " ".join(f"*{ext}" for ext in MEDIA_EXTS) + ")"

if sys.platform == "win32":
    UI_FONT = '"Segoe UI", sans-serif'
    MONO_FONT = '"Cascadia Code", "Cascadia Mono", "Consolas", monospace'
    SYMBOL_FONT = '"Segoe UI Symbol", "Segoe UI", sans-serif'
else:
    UI_FONT = '"Ubuntu", "Cantarell", "Noto Sans", "DejaVu Sans", sans-serif'
    MONO_FONT = '"Ubuntu Mono", "DejaVu Sans Mono", "Liberation Mono", monospace'
    SYMBOL_FONT = '"Ubuntu", "Noto Sans Symbols 2", "DejaVu Sans", sans-serif'

MOCKUP_STYLE = f"""
QMainWindow, QWidget#central_content {{
    background-color: #141518;
    color: #e6e6e6;
    font-family: {UI_FONT};
    font-size: 13px;
}}
QMenuBar {{
    background-color: #1d1f23;
    color: #e6e6e6;
    max-height: 0px;
    border: none;
    padding: 0px;
    margin: 0px;
}}
QWidget#top_toolbar {{
    background-color: #1d1f23;
    border-bottom: 1px solid #2a2d33;
}}
QPushButton[role="tbtn"] {{
    background-color: transparent;
    border: 1px solid transparent;
    color: #e6e6e6;
    border-radius: 6px;
    padding: 4px 7px;
    font-family: {UI_FONT};
    font-size: 15px;
}}
QPushButton[role="tbtn"]:hover {{
    background-color: #2c2f36;
    border-color: #2c2f36;
}}
QPushButton[role="tbtn"]:pressed {{
    background-color: #363a42;
    border-color: #363a42;
}}
QFrame[role="tsep"] {{
    background-color: #2a2d33;
    min-width: 1px;
    max-width: 1px;
    min-height: 24px;
    max-height: 24px;
    margin: 0px 2px;
}}
QLineEdit#location_bar {{
    background-color: #101114;
    border: 1px solid #2f333a;
    border-radius: 6px;
    padding: 5px 9px;
    color: #e6e6e6;
    font-family: {MONO_FONT};
    font-size: 12px;
    min-width: 300px;
}}
QLineEdit#location_bar:focus {{
    border-color: #4c8dff;
}}
QTabWidget::pane {{
    border: none;
    background-color: #000000;
}}
QWidget#canvas_placeholder {{
    background-color: #000000;
}}
QLabel#placeholder_label {{
    color: #8b9099;
    font-family: {UI_FONT};
    font-size: 14px;
    background: transparent;
}}
QWidget#bottom_panel {{
    background-color: #1d1f23;
    border-top: 1px solid #2a2d33;
}}
QLabel[role="time_text"] {{
    font-family: {MONO_FONT};
    color: #c9cdd4;
    font-size: 12px;
    min-width: 96px;
    background: transparent;
}}
QSlider#seek_bar {{
    min-height: 18px;
    max-height: 18px;
    background: transparent;
}}
QSlider#seek_bar::groove:horizontal {{
    height: 6px;
    background: #2f333a;
    border-radius: 3px;
}}
QSlider#seek_bar::sub-page:horizontal {{
    height: 6px;
    background: #4c8dff;
    border-radius: 3px;
}}
QSlider#seek_bar::add-page:horizontal {{
    height: 6px;
    background: #2f333a;
    border-radius: 3px;
}}
QSlider#seek_bar::handle:horizontal {{
    width: 14px;
    height: 14px;
    margin: -4px 0px;
    background: #ffffff;
    border-radius: 7px;
    border: none;
}}
QPushButton[role="cbtn"], QPushButton[role="cbtn_sm"] {{
    background-color: transparent;
    border: 1px solid transparent;
    color: #e6e6e6;
    border-radius: 6px;
    min-width: 28px;
    min-height: 26px;
    padding: 2px 6px;
    font-family: {SYMBOL_FONT};
    font-size: 16px;
}}
QPushButton[role="cbtn_sm"] {{
    font-size: 11px;
}}
QPushButton[role="cbtn"]:hover, QPushButton[role="cbtn_sm"]:hover {{
    background-color: #2c2f36;
    border-color: #2c2f36;
}}
QPushButton[role="cbtn"]:pressed, QPushButton[role="cbtn_sm"]:pressed {{
    background-color: #363a42;
    border-color: #363a42;
}}
QPushButton#play_btn {{
    background-color: #4c8dff;
    color: #ffffff;
    border: 1px solid #4c8dff;
    border-radius: 14px;
    min-width: 34px;
    max-width: 34px;
    min-height: 26px;
    max-height: 26px;
    padding: 0px;
    font-family: {SYMBOL_FONT};
    font-size: 12px;
}}
QPushButton#play_btn:hover {{
    background-color: #6aa1ff;
    border-color: #6aa1ff;
}}
QPushButton#play_btn:pressed {{
    background-color: #363a42;
    border-color: #363a42;
}}
QComboBox#speed_sel {{
    background-color: #24262b;
    border: 1px solid #2f333a;
    border-radius: 6px;
    color: #e6e6e6;
    padding: 3px 22px 3px 10px;
    min-height: 20px;
    font-family: {UI_FONT};
    font-size: 12px;
}}
QComboBox#speed_sel:hover {{
    background-color: #2c2f36;
    border-color: #3a3f48;
}}
QComboBox#speed_sel::drop-down {{
    border: none;
    background: transparent;
    width: 18px;
}}
QComboBox#speed_sel::down-arrow {{
    image: none;
    border: none;
}}
QComboBox#speed_sel QAbstractItemView {{
    background-color: #24262b;
    color: #e6e6e6;
    selection-background-color: #4c8dff;
    border: 1px solid #2f333a;
}}
QLabel#frame_label {{
    font-family: {MONO_FONT};
    font-weight: bold;
    color: #ffffff;
    padding: 0px 6px;
    font-size: 12px;
    background: transparent;
}}
QLabel#meta_label {{
    font-family: {UI_FONT};
    color: #8b9099;
    font-size: 12px;
    background: transparent;
}}
QStatusBar {{
    background-color: #141518;
    border-top: 1px solid #2a2d33;
    color: #8b9099;
    font-family: {UI_FONT};
    font-size: 12px;
}}
QStatusBar::item {{
    border: none;
}}
QLabel#coords_label {{
    font-family: {MONO_FONT};
    color: #8b9099;
    font-size: 12px;
    padding: 0px 8px;
}}
QLabel#zoom_label {{
    font-family: {UI_FONT};
    color: #8b9099;
    font-size: 12px;
    padding: 0px 8px;
}}
"""


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


class ControlBar(QWidget):
    def __init__(self, parent, play_button: QPushButton):
        super().__init__(parent)
        self.hide()
        self.play_action = QAction("Play", self)
        self.play_action.setShortcut("Space")
        self.play_action.setEnabled(False)
        self.play_action.triggered.connect(lambda: parent.player.play_pause())
        parent.addAction(self.play_action)
        self.play_button = play_button
        self.play_button.setAccessibleName("Play or pause")
        self.play_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self.play_action.trigger)
        self.play_action.changed.connect(
            lambda: self.play_button.setEnabled(self.play_action.isEnabled()),
        )

    def widgetForAction(self, action):
        return self.play_button if action is self.play_action else None


class SpeedCombo(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(self.palette().text().color()))
        painter.drawText(
            self.rect().adjusted(0, 0, -8, 0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "▾",
        )


def _make_btn(text: str, tooltip: str, accessible_name: str, role: str, parent: QWidget) -> QPushButton:
    btn = QPushButton(text, parent)
    btn.setProperty("role", role)
    btn.setToolTip(tooltip)
    btn.setAccessibleName(accessible_name)
    btn.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def _make_sep(parent: QWidget) -> QFrame:
    sep = QFrame(parent)
    sep.setProperty("role", "tsep")
    sep.setFrameShape(QFrame.Shape.VLine)
    return sep


class MainWindow(QMainWindow):
    _retry_completed = Signal(object, object, object, object)
    _tab_fields: ClassVar[dict[str, str]] = {
        "_current_file": "current_file",
        "_active_transport": "active_transport",
        "_transports": "transports",
        "_pending_recent": "pending_recent",
        "_remote_details": "remote_details",
        "_failed_position": "failed_position",
        "_retry_cancel": "retry_cancel",
        "_reconnect_attempt": "reconnect_attempt",
        "_cache_paused": "cache_paused",
        "_duration": "duration",
        "_position": "position",
    }

    def __init__(self, settings: Settings | None = None, *, controller=None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(960, 600)
        self.setStyleSheet(MOCKUP_STYLE)
        self.controller = controller
        self.settings = settings or Settings()
        self.settings.load()
        self._current_file: Path | None = None
        self._active_transport = None
        self._transports = []
        self._pending_recent: tuple[str, str] | None = None
        self._connect_dialog = None
        self._remote_details = None
        self._failed_position = None
        self._retry_cancel = None
        self._closing = False
        self._reconnect_attempt = None
        self._cache_paused = False
        self.player = None
        self.video = None
        self._active_tab = None

        self.statusBar().setSizeGripEnabled(False)
        self.coords_label = QLabel("x: 960, y: 540", self)
        self.coords_label.setObjectName("coords_label")
        self.coords_label.setAccessibleName("Cursor coordinates")
        self.statusBar().addWidget(self.coords_label)
        self.zoom_label = QLabel("100%", self)
        self.zoom_label.setObjectName("zoom_label")
        self.zoom_label.setAccessibleName("Zoom level")
        self.statusBar().addWidget(self.zoom_label)
        self.speed_label = QLabel("1×", self)
        self.speed_label.setAccessibleName("Playback speed")
        self.speed_label.setStyleSheet("color: transparent; background: transparent; font-size: 1px;")
        self.speed_label.setFixedWidth(2)
        self.statusBar().addPermanentWidget(self.speed_label)
        self._retry_completed.connect(self._finish_remote_retry)
        self.connection_status = QLabel(self)
        self.connection_status.setAccessibleName("Remote connection status")
        self.connection_status.hide()
        self.statusBar().addPermanentWidget(self.connection_status)
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
        content.setObjectName("central_content")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.top_toolbar = QWidget(content)
        self.top_toolbar.setObjectName("top_toolbar")
        self.top_toolbar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        toolbar_layout = QHBoxLayout(self.top_toolbar)
        toolbar_layout.setContentsMargins(6, 4, 6, 4)
        toolbar_layout.setSpacing(4)
        self.open_btn = _make_btn("Open File", "Open file (Ctrl+O)", "Open file", "tbtn", self.top_toolbar)
        self.open_btn.clicked.connect(self.choose_file)
        toolbar_layout.addWidget(self.open_btn)
        self.location_bar = QLineEdit(self.top_toolbar)
        self.location_bar.setObjectName("location_bar")
        self.location_bar.setPlaceholderText("/path/video.mp4  or  sftp://user@host/path/video.mp4  (Enter to load)")
        self.location_bar.setAccessibleName("Video path or SFTP URI")
        self.location_bar.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.location_bar.returnPressed.connect(self._open_from_location)
        toolbar_layout.addWidget(self.location_bar, 1)
        toolbar_layout.addWidget(_make_sep(self.top_toolbar))
        self.save_frame_btn = _make_btn("💾", "Save frame as PNG (Ctrl+S)", "Save frame as PNG", "tbtn", self.top_toolbar)
        self.save_frame_btn.clicked.connect(self.snapshot)
        toolbar_layout.addWidget(self.save_frame_btn)
        self.copy_frame_btn = _make_btn("📋", "Copy frame to clipboard (Ctrl+Shift+C)", "Copy frame to clipboard", "tbtn", self.top_toolbar)
        toolbar_layout.addWidget(self.copy_frame_btn)
        toolbar_layout.addWidget(_make_sep(self.top_toolbar))
        self.fit_btn = _make_btn("⛶", "Fit to window (Ctrl+0)", "Fit to window", "tbtn", self.top_toolbar)
        toolbar_layout.addWidget(self.fit_btn)
        self.actual_size_btn = _make_btn("1:1", "Actual pixels 1:1 (Ctrl+1)", "Actual pixels 1:1", "tbtn", self.top_toolbar)
        toolbar_layout.addWidget(self.actual_size_btn)
        self.fullscreen_btn = _make_btn("⛶", "Fullscreen (F11)", "Fullscreen", "tbtn", self.top_toolbar)
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        toolbar_layout.addWidget(self.fullscreen_btn)
        toolbar_layout.addWidget(_make_sep(self.top_toolbar))
        self.help_btn = _make_btn("?", "Keyboard shortcuts (F1)", "Keyboard shortcuts", "tbtn", self.top_toolbar)
        toolbar_layout.addWidget(self.help_btn)
        layout.addWidget(self.top_toolbar)

        self.limit_message = QLabel(content)
        self.limit_message.setAccessibleName("Tab limit")
        self.limit_message.setWordWrap(True)
        self.limit_message.hide()
        layout.addWidget(self.limit_message)
        self.limit_button = QPushButton("Open in new window", content)
        self.limit_button.setAccessibleName("Open file in new window")
        self.limit_button.clicked.connect(self._open_overflow_window)
        self.limit_button.hide()
        layout.addWidget(self.limit_button)
        self._overflow_path = None
        self.banner = QLabel(content)
        self.banner.setAccessibleName("Playback error")
        self.banner.setWordWrap(True)
        self.banner.hide()
        layout.addWidget(self.banner)
        self.retry_button = QPushButton("Retry", content)
        self.retry_button.setAccessibleName("Retry remote connection")
        self.retry_button.clicked.connect(self._retry_remote)
        self.retry_button.hide()
        layout.addWidget(self.retry_button)
        self.tabs = DetachableTabWidget(content)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(self._close_tab_at)
        self.tabs.open_requested.connect(self.choose_file)
        self.tabs.connect_requested.connect(self._ask_remote_uri)
        self.tabs.detach_requested.connect(self._detach_tab)
        layout.addWidget(self.tabs, 1)
        self.video_focus = QFocusFrame(content)
        self.video_focus.hide()
        QApplication.instance().focusChanged.connect(self._focus_changed)

        self.bottom_panel = QWidget(content)
        self.bottom_panel.setObjectName("bottom_panel")
        self.bottom_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel_layout = QVBoxLayout(self.bottom_panel)
        panel_layout.setContentsMargins(12, 6, 12, 8)
        panel_layout.setSpacing(4)

        seek_row = QHBoxLayout()
        seek_row.setContentsMargins(0, 0, 0, 0)
        seek_row.setSpacing(8)
        self.pos_time_label = QLabel("00:00:00.000", self.bottom_panel)
        self.pos_time_label.setProperty("role", "time_text")
        self.pos_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pos_time_label.setAccessibleName("Current playback time")
        seek_row.addWidget(self.pos_time_label)
        self.seek_bar = SeekBar(self.bottom_panel)
        self.seek_bar.setObjectName("seek_bar")
        seek_row.addWidget(self.seek_bar, 1)
        self.dur_time_label = QLabel("00:00:00.000", self.bottom_panel)
        self.dur_time_label.setProperty("role", "time_text")
        self.dur_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dur_time_label.setAccessibleName("Total duration")
        seek_row.addWidget(self.dur_time_label)
        panel_layout.addLayout(seek_row)

        ctrl_row = QHBoxLayout()
        ctrl_row.setContentsMargins(0, 0, 0, 0)
        ctrl_row.setSpacing(2)
        self.first_frame_btn = _make_btn("⏮\ufe0e", "First frame (Home)", "First frame", "cbtn", self.bottom_panel)
        ctrl_row.addWidget(self.first_frame_btn)
        self.step_back_10_btn = _make_btn("⏪\ufe0e", "−10 frames (Shift+←)", "Skip frames back", "cbtn", self.bottom_panel)
        ctrl_row.addWidget(self.step_back_10_btn)
        self.step_back_1_btn = _make_btn("◀\ufe0e", "−1 frame (←)", "Previous frame", "cbtn_sm", self.bottom_panel)
        ctrl_row.addWidget(self.step_back_1_btn)
        ctrl_row.addSpacing(4)
        play_btn = QPushButton("▶\ufe0e", self.bottom_panel)
        play_btn.setObjectName("play_btn")
        play_btn.setToolTip("Play / pause (Space)")
        play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ctrl_row.addWidget(play_btn)
        ctrl_row.addSpacing(4)
        self.step_fwd_1_btn = _make_btn("▶\ufe0e", "+1 frame (→)", "Next frame", "cbtn_sm", self.bottom_panel)
        ctrl_row.addWidget(self.step_fwd_1_btn)
        self.step_fwd_10_btn = _make_btn("⏩\ufe0e", "+10 frames (Shift+→)", "Skip frames forward", "cbtn", self.bottom_panel)
        ctrl_row.addWidget(self.step_fwd_10_btn)
        self.last_frame_btn = _make_btn("⏭\ufe0e", "Last frame (End)", "Last frame", "cbtn", self.bottom_panel)
        ctrl_row.addWidget(self.last_frame_btn)
        ctrl_row.addSpacing(20)
        self.speed_combo = SpeedCombo(self.bottom_panel)
        self.speed_combo.setObjectName("speed_sel")
        self.speed_combo.setToolTip("Playback speed ( [ / ] )")
        self.speed_combo.setAccessibleName("Playback speed selector")
        self.speed_combo.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        for rate in SPEED_OPTIONS:
            self.speed_combo.addItem(f"{rate:g}×", rate)
        self.speed_combo.setCurrentIndex(SPEED_OPTIONS.index(1.0))
        self.speed_combo.activated.connect(self._select_speed_from_combo)
        ctrl_row.addWidget(self.speed_combo)
        ctrl_row.addSpacing(4)
        self.goto_frame_btn = _make_btn("↗\ufe0e", "Go to frame (G)", "Go to frame", "cbtn", self.bottom_panel)
        ctrl_row.addWidget(self.goto_frame_btn)
        self.frame_label = QLabel("frame — / —", self.bottom_panel)
        self.frame_label.setObjectName("frame_label")
        self.frame_label.setAccessibleName("Frame counter")
        ctrl_row.addWidget(self.frame_label)
        ctrl_row.addStretch(1)
        self.meta_label = QLabel("—", self.bottom_panel)
        self.meta_label.setObjectName("meta_label")
        self.meta_label.setAccessibleName("Video metadata")
        ctrl_row.addWidget(self.meta_label)
        panel_layout.addLayout(ctrl_row)
        layout.addWidget(self.bottom_panel)

        self.time_label = QLabel("00:00:00.000 / 00:00:00.000 · f —", content)
        self.time_label.setAccessibleName("Playback position")
        self.time_label.setFixedSize(0, 0)
        layout.addWidget(self.time_label)
        self.setCentralWidget(content)

        self.controls = ControlBar(self, play_btn)
        self.browser = BrowserDock(self)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.browser)
        self.browser.hide()
        self.browser.file_activated.connect(self.open_file)
        self._suggestions = QStringListModel(self.location_bar)
        completer = QCompleter(self._suggestions, self.location_bar)
        completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        completer.popup().setAccessibleName("Video files in directory")
        self.location_bar.setCompleter(completer)
        completer.activated[str].connect(self.open_file)
        self.location_bar.textEdited.connect(self._suggest_videos)
        QWidget.setTabOrder(self.browser.all_files, self.browser.tree)
        QWidget.setTabOrder(self.browser.tree, self.tabs)
        QWidget.setTabOrder(self.tabs, self.seek_bar)
        QWidget.setTabOrder(self.seek_bar, self.controls.play_button)
        QWidget.setTabOrder(self.controls.play_button, self.browser.all_files)
        open_action = QAction("&Open...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.choose_file)
        self.file_menu = self.menuBar().addMenu("&File")
        self.file_menu.addAction(open_action)
        new_window_action = QAction("New window", self)
        new_window_action.setShortcut("Ctrl+N")
        new_window_action.triggered.connect(self.new_window)
        self.file_menu.addAction(new_window_action)
        self.recent_menu = self.file_menu.addMenu("Recent Files")
        self.recent_menu.aboutToShow.connect(self._refresh_recent_menu)
        self._refresh_recent_menu()
        preferences_action = QAction("Preferences...", self)
        preferences_action.triggered.connect(self.show_preferences)
        self.file_menu.addAction(preferences_action)
        new_tab_action = QAction("New tab...", self)
        new_tab_action.setShortcut("Ctrl+T")
        new_tab_action.triggered.connect(self.new_tab)
        self.file_menu.addAction(new_tab_action)
        self.move_tab_action = QAction("Move tab to new window", self)
        self.move_tab_action.setShortcut("Ctrl+Shift+N")
        self.move_tab_action.triggered.connect(lambda: self._detach_tab(self.tabs.currentWidget()))
        self.file_menu.addAction(self.move_tab_action)
        self.copy_position_action = QAction("Copy position", self)
        self.copy_position_action.setObjectName("copy_position")
        self.copy_position_action.setShortcut("Ctrl+Shift+C")
        self.copy_position_action.triggered.connect(self.copy_position)
        self.file_menu.addAction(self.copy_position_action)
        close_tab_action = QAction("Close tab", self)
        close_tab_action.setShortcut("Ctrl+W")
        close_tab_action.triggered.connect(self.close_tab)
        self.file_menu.addAction(close_tab_action)
        for label, shortcut, callback in (
            ("Next tab", "Ctrl+Tab", self.next_tab),
            ("Previous tab", "Ctrl+Shift+Tab", self.prev_tab),
        ):
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            self.file_menu.addAction(action)
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
        self.playback_menu.addAction(self.frame_next)
        self.frame_prev = QAction("Previous frame", self)
        self.frame_prev.setObjectName("frame_prev")
        self.frame_prev.setShortcut(",")
        self.frame_prev.setEnabled(False)
        self.frame_prev.triggered.connect(lambda: self.player.frame_step(-1))
        self.playback_menu.addAction(self.frame_prev)
        self.first_frame_action = QAction("First frame", self)
        self.first_frame_action.setShortcut("Home")
        self.first_frame_action.setEnabled(False)
        self.first_frame_action.triggered.connect(lambda: self._seek_edge(False))
        self.playback_menu.addAction(self.first_frame_action)
        self.last_frame_action = QAction("Last frame", self)
        self.last_frame_action.setShortcut("End")
        self.last_frame_action.setEnabled(False)
        self.last_frame_action.triggered.connect(lambda: self._seek_edge(True))
        self.playback_menu.addAction(self.last_frame_action)
        self.skip_actions = []
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
            self.skip_actions.append(action)
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
            ("Mute", "M", lambda: self.player.toggle_mute()),
            ("Fullscreen", "F", self.toggle_fullscreen),
            ("Exit fullscreen", "Esc", self.exit_fullscreen),
        ):
            action = QAction(label, self)
            action.setShortcut(key)
            action.triggered.connect(callback)
            self.playback_menu.addAction(action)
        self._duration = 0.0
        self._position = 0.0
        self.seek_bar.seek_requested.connect(self._seek_from_bar)
        for name, label, shortcut, callback in (
            ("ab_set_a", "Set loop start (A)", "Ctrl+Alt+1", lambda: self.player.set_ab_point("a")),
            ("ab_set_b", "Set loop end (B)", "Ctrl+Alt+2", lambda: self.player.set_ab_point("b")),
            ("ab_clear", "Clear A-B loop", "Ctrl+Alt+0", lambda: self.player.clear_ab_loop()),
        ):
            action = QAction(label, self)
            action.setObjectName(name)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            self.playback_menu.addAction(action)
        self.step_fwd_1_btn.clicked.connect(self.frame_next.trigger)
        self.step_back_1_btn.clicked.connect(self.frame_prev.trigger)
        self.step_fwd_10_btn.clicked.connect(self.skip_actions[0].trigger)
        self.step_back_10_btn.clicked.connect(self.skip_actions[1].trigger)
        self.first_frame_btn.clicked.connect(self.first_frame_action.trigger)
        self.last_frame_btn.clicked.connect(self.last_frame_action.trigger)
        for menu in (self.file_menu, self.view_menu, self.playback_menu, self.audio_menu, self.subtitle_menu):
            for action in menu.actions():
                self.addAction(action)
        self._tab_changed(-1)

    def _open_from_location(self):
        target = self.location_bar.text().strip()
        if target:
            if not target.lower().startswith("sftp://") and Path(target).is_dir():
                self._suggest_videos(target)
            else:
                self.open_file(target)

    def _suggest_videos(self, target: str):
        folder = Path(target.strip())
        files = []
        if not target.lower().startswith("sftp://") and folder.is_dir():
            try:
                files = sorted(
                    (str(path) for path in folder.iterdir()
                     if path.suffix.lower() in MEDIA_EXTS and path.is_file()),
                    key=str.casefold,
                )
            except OSError as error:
                self.show_error(f"Could not list video files in {folder}: {error}")
        self._suggestions.setStringList(files)
        if files:
            self.location_bar.completer().complete()
        else:
            self.location_bar.completer().popup().hide()

    def _seek_edge(self, last: bool):
        self.player.mpv.pause = True
        self.player.seek(self.player.mpv.duration if last else 0)

    def _select_speed_from_combo(self, index: int):
        if self.player is not None:
            self.player.set_speed(self.speed_combo.itemData(index))

    def _sync_speed_ui(self, speed: float):
        text = f"{speed:g}×"
        self.speed_label.setText(text)
        index = self.speed_combo.findText(text)
        if index >= 0:
            self.speed_combo.setCurrentIndex(index)

    def _add_player_tab(self, name: str) -> PlayerTab:
        player = Player(
            self, readahead_mb=self.settings.readahead_mb, backbuffer_mb=self.settings.backbuffer_mb,
            retry_max=self.settings.retry_max,
            snapshot_dir=self.settings.snapshot_dir, jpeg_quality=self.settings.jpeg_quality,
            hwdec=self.settings.hwdec,
        )
        player.mpv.audio_pitch_correction = self.settings.pitch_correction
        tab = PlayerTab(player, owner=self)

        def active(signal, callback, hidden=None):
            signal.connect(
                lambda *args: callback(tab.owner, *args) if tab.owner._active_tab is tab
                else hidden(tab.owner, *args) if hidden is not None and shiboken6.isValid(tab) else None,
            )

        active(player.speed_changed, lambda window, speed: window._sync_speed_ui(speed))
        active(player.file_loaded, lambda window: window._refresh_tracks())
        active(player.file_loaded, lambda window: window._update_metadata())
        player.file_loaded.connect(lambda: tab.owner._file_opened(tab))
        active(player.file_loaded, lambda window: window.banner.hide(), lambda _window: setattr(tab, "banner_visible", False))
        active(player.file_loaded, lambda window: window.controls.play_action.setEnabled(True))
        active(player.file_loaded, lambda window: window.frame_next.setEnabled(True))
        active(player.file_loaded, lambda window: window.frame_prev.setEnabled(True))
        active(player.file_loaded, lambda window: window.first_frame_action.setEnabled(True))
        active(player.file_loaded, lambda window: window.last_frame_action.setEnabled(True))
        for index in range(len(self.skip_actions)):
            active(player.file_loaded, lambda window, index=index: window.skip_actions[index].setEnabled(True))
        active(
            player.paused,
            lambda window, paused: window.controls.play_action.setText("Play" if paused else "Pause"),
        )
        player.sftp_open_failed.connect(lambda uri: tab.owner._remote_open_failed(uri, tab))
        player.sftp_reconnecting.connect(
            lambda uri, attempt: tab.owner._remote_reconnecting(uri, attempt, tab),
        )
        player.sftp_reconnected.connect(lambda uri: tab.owner._remote_reconnected(uri, tab))
        player.sftp_retry_failed.connect(lambda uri: tab.owner._remote_retry_failed(uri, tab))
        active(
            player.connection_failed,
            lambda window, position: window._connection_failed(position),
            lambda window, position: window._connection_failed_for_tab(tab, position),
        )
        player.sftp_transport_changed.connect(
            lambda uri, previous, replacement: tab.owner._transport_reconnected(
                uri, previous, replacement, tab,
            ),
        )
        player.cache_paused.connect(lambda paused: tab.owner._cache_pause_changed(paused, tab))
        active(player.skip_status, lambda window, message: window.statusBar().showMessage(message))
        active(
            player.error,
            lambda window, message: window.show_error(message),
            lambda window, message: window._show_tab_error(tab, message),
        )
        active(player.duration, lambda window, duration: window._duration_changed(duration))
        active(player.loop_points_changed, lambda window, *_args: window._update_loop_markers())
        active(player.position, lambda window, position: window._position_changed(position))
        active(player.vfr_detected, lambda window, *_args: window._update_time())
        active(player.vfr_detected, lambda window, *_args: window._update_metadata())
        self.tabs.new_tab(tab, name)
        QWidget.setTabOrder(self.browser.tree, tab.video)
        QWidget.setTabOrder(tab.video, self.seek_bar)
        return tab

    def _store_active_tab_state(self):
        if self._active_tab is None:
            return
        for field, attribute in self._tab_fields.items():
            setattr(self._active_tab, attribute, getattr(self, field))
        self._active_tab.banner_text = self.banner.text()
        self._active_tab.banner_visible = not self.banner.isHidden()
        self._active_tab.retry_visible = not self.retry_button.isHidden()

    def _tab_changed(self, index):
        previous = self._active_tab
        self._store_active_tab_state()
        tab = self.tabs.widget(index)
        if previous is not None and previous is not tab:
            self._hide_background_tab(previous)
        if previous is not None and previous is not tab and previous.retry_cancel is not None:
            previous.retry_cancel.set()
            previous.retry_cancel = None
            self.retry_button.setEnabled(True)
        self._active_tab = tab
        if tab is not None:
            if self.isMinimized() and not QApplication.platformName().lower().startswith("wayland"):
                self._hide_background_tab(tab)
            else:
                self._show_background_tab(tab)
        self.player = tab.player if tab else None
        self.video = tab.video if tab else None
        if tab is None:
            self.banner.hide()
            self.retry_button.hide()
            self.connection_status.hide()
            self._duration = self._position = 0.0
            self._current_file = self._active_transport = self._pending_recent = None
            self._remote_details = self._failed_position = self._retry_cancel = None
            self._reconnect_attempt = None
            self._transports = []
            self._cache_paused = False
            self._sync_speed_ui(1.0)
            self.location_bar.clear()
            self.pos_time_label.setText("00:00:00.000")
            self.dur_time_label.setText("00:00:00.000")
            self.frame_label.setText("frame — / —")
            self.time_label.setText("00:00:00.000 / 00:00:00.000 · f —")
            self.seek_bar.set_loop_points(None, None, 0)
        else:
            for field, attribute in self._tab_fields.items():
                setattr(self, field, getattr(tab, attribute))
            self._position = tab.player.mpv.time_pos or self._position
            self._duration = tab.player.mpv.duration or self._duration
            self.banner.setText(tab.banner_text)
            self.banner.setVisible(tab.banner_visible)
            self.retry_button.setVisible(tab.retry_visible)
            self._update_connection_status()
            self._sync_speed_ui(self.player.mpv.speed)
            self.location_bar.setText(
                str(self._current_file) if self._current_file is not None
                else self._remote_details[0] if self._remote_details is not None else "",
            )
            self._update_time()
            self._update_loop_markers()
            if previous is not None and self.video.isVisible():
                self.video.setFocus()
        loaded = tab is not None and self.player.mpv.duration is not None
        self._update_metadata()
        self.move_tab_action.setEnabled(tab is not None)
        self.copy_position_action.setEnabled(tab is not None)
        self.seek_bar.setEnabled(loaded)
        for action in self.playback_menu.actions():
            if action.text() not in ("Fullscreen", "Exit fullscreen"):
                action.setEnabled(tab is not None)
        for action in (
            self.controls.play_action, self.frame_next, self.frame_prev,
            self.first_frame_action, self.last_frame_action, *self.skip_actions,
        ):
            action.setEnabled(loaded)
        if tab is not None:
            self.controls.play_action.setText("Play" if self.player.mpv.pause else "Pause")
        self._refresh_tracks()

    def _hide_background_tab(self, tab):
        if tab.background_mode is not None:
            return
        tab.background_mode = self.settings.background_tabs
        if tab.background_mode == "pause":
            tab.background_playing = not tab.player.mpv.pause
            if tab.background_playing:
                tab.player.mpv.pause = True
        elif tab.background_mode == "muted":
            tab.background_muted = tab.player.mpv.mute
            tab.player.mpv.mute = True

    def _show_background_tab(self, tab):
        if tab.background_mode == "pause" and tab.background_playing:
            tab.player.mpv.pause = False
        elif tab.background_mode == "muted":
            tab.player.mpv.mute = tab.background_muted
        tab.background_mode = None

    def changeEvent(self, event):
        if (
            event.type() == QEvent.Type.WindowStateChange
            and not QApplication.platformName().lower().startswith("wayland")
            and self._active_tab is not None
        ):
            if self.isMinimized():
                self._hide_background_tab(self._active_tab)
            else:
                self._show_background_tab(self._active_tab)
        super().changeEvent(event)

    def new_tab(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Video", "", VIDEO_FILTER)
        if path:
            from vplayer.app import open_in_window

            open_in_window(self, path, new_tab=True)

    def show_tab_limit(self, path):
        self._overflow_path = path
        self.limit_message.setText("This window has 4 tabs. Close one, or open in a new window")
        self.limit_message.show()
        self.limit_button.show()

    def _open_overflow_window(self):
        if self._overflow_path is None:
            return
        path = self._overflow_path
        self._overflow_path = None
        self.limit_message.hide()
        self.limit_button.hide()
        self.new_window().open_file(path)

    def new_window(self):
        if self.controller is None:
            from vplayer.app import AppController

            self.controller = AppController(QApplication.instance())
            self.controller.register(self)
        return self.controller.new_window()

    def receive_tab(self, source, tab):
        if source is self or self._closing or source._closing:
            return False
        if self.tabs.count() >= 4:
            return False
        if self.controller is None or source.controller is not self.controller:
            raise RuntimeError("Tab moves require windows owned by the same application")
        return self.controller.move_tab(source, self, tab)

    def _detach_tab(self, tab):
        if self._closing or not isinstance(tab, PlayerTab) or not shiboken6.isValid(tab) or self.tabs.indexOf(tab) < 0:
            return
        target = self.new_window()
        self.controller.move_tab(self, target, tab)

    def close_tab(self):
        index = self.tabs.currentIndex()
        if index < 0:
            return
        self._save_position()
        if self._retry_cancel is not None:
            self._retry_cancel.set()
        self.tabs.close_tab(index)
        if self.tabs.count() < 4:
            self._overflow_path = None
            self.limit_message.hide()
            self.limit_button.hide()

    def _close_tab_at(self, index):
        self.tabs.setCurrentIndex(index)
        self.close_tab()

    def next_tab(self):
        self.tabs.next_tab()

    def prev_tab(self):
        self.tabs.prev_tab()

    def _ask_remote_uri(self):
        uri, accepted = QInputDialog.getText(self, "Connect to server", "SFTP URI")
        if accepted and uri:
            self.open_file(uri)

    @staticmethod
    def _clock(seconds: float) -> str:
        if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
            return "—"
        whole, millis = divmod(round(seconds * 1000), 1000)
        hours, remainder = divmod(whole, 3600)
        minutes, second = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{second:02}.{millis:03}"

    def copy_position(self):
        if self.player is None or self.player._uri is None:
            self.show_error("Open a video to copy its position")
            return
        position = self._position
        if not isinstance(position, (int, float)) or not math.isfinite(position) or position < 0:
            self.show_error("Current position is unavailable")
            return
        timestamp = self._clock(position)
        fps = self.player.frame_rate()
        text = f"{timestamp} f{round(position * fps)}" if fps is not None else timestamp
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("Position copied to clipboard", 3000)

    def _update_time(self):
        fps = self.player.frame_rate()
        pos_text = self._clock(self._position)
        dur_text = self._clock(self._duration)
        self.pos_time_label.setText(pos_text)
        self.dur_time_label.setText(dur_text)
        if fps is None:
            frame = "f —"
            self.frame_label.setText("frame — / —")
        else:
            cur_frame = round(self._position * fps)
            total_frames = round(self._duration * fps) if self._duration > 0 else "—"
            frame = f"≈ f {cur_frame}" if self.player.variable_frame_rate else f"f{cur_frame}"
            prefix = "≈ frame" if self.player.variable_frame_rate else "frame"
            self.frame_label.setText(f"{prefix} {cur_frame} / {total_frames}")
        self.time_label.setText(f"{pos_text} / {dur_text} · {frame}")

    def _update_metadata(self):
        if self.player is None or self.player.mpv.duration is None:
            self.meta_label.setText("—")
            return
        params = self.player.mpv.video_params or {}
        if not params:
            self.meta_label.setText("—")
            return
        details = []
        if params.get("w") and params.get("h"):
            details.append(f"{params['w']}×{params['h']}")
        fps = self.player.frame_rate()
        if fps is not None:
            details.append(f"{'≈ ' if self.player.variable_frame_rate else ''}{fps:.3f} fps")
        codec = next(
            (track.get("codec") for track in self.player.mpv.track_list
             if track.get("type") == "video" and track.get("selected")),
            None,
        )
        if codec:
            details.append(codec)
        self.meta_label.setText(" · ".join(details) or "—")

    def _duration_changed(self, duration):
        if self.sender() is not None and self.sender() is not self.player:
            return
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
        if self.video is not None and current is self.video:
            self.video_focus.setWidget(self.video)
            self.video_focus.show()
        else:
            self.video_focus.setWidget(None)
            self.video_focus.hide()

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Video", "", VIDEO_FILTER)
        if path:
            self.open_file(path)

    def show_preferences(self):
        dialog = self.findChild(PreferencesDialog)
        if dialog is not None and dialog.isVisible():
            dialog.raise_()
            dialog.activateWindow()
            return
        dialog = PreferencesDialog(
            self.settings.pitch_correction, self, resume_enabled=self.settings.resume_enabled,
            background_tabs=self.settings.background_tabs, hwdec=self.settings.hwdec,
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.accepted.connect(lambda: self._save_pitch_preference(dialog.pitch_correction.isChecked()))
        dialog.accepted.connect(lambda: self._save_resume_preference(dialog.resume_enabled.isChecked()))
        dialog.accepted.connect(lambda: self._save_background_preference(dialog.background_tabs.currentData()))
        dialog.accepted.connect(lambda: self._save_hwdec_preference(dialog.hwdec.currentData()))
        dialog.open()

    def _save_hwdec_preference(self, mode: str):
        try:
            self.settings.set_hwdec(mode)
            windows = self.controller.windows if self.controller is not None else [self]
            for window in windows:
                if window._closing:
                    continue
                window.settings.hwdec = mode
                for index in range(window.tabs.count()):
                    player = window.tabs.widget(index).player
                    player.hwdec = mode
                    player.mpv.hwdec = mode
        except (OSError, RuntimeError, SystemError, mpv.PropertyUnavailableError) as error:
            self.show_error(f"Could not apply hardware decoding preference: {error}")

    def _save_pitch_preference(self, enabled: bool):
        try:
            for index in range(self.tabs.count()):
                self.tabs.widget(index).player.mpv.audio_pitch_correction = enabled
            self.settings.set_pitch_correction(enabled)
        except (OSError, RuntimeError, SystemError, mpv.PropertyUnavailableError) as error:
            self.show_error(f"Could not save pitch correction: {error}")

    def _save_resume_preference(self, enabled: bool):
        try:
            self.settings.set_resume_enabled(enabled)
        except OSError as error:
            self.show_error(f"Could not save resume preference: {error}")

    def _save_background_preference(self, mode: str):
        try:
            self.settings.set_background_tabs(mode)
            windows = self.controller.windows if self.controller is not None else [self]
            for window in windows:
                if window._closing:
                    continue
                window.settings.background_tabs = mode
                for index in range(window.tabs.count()):
                    tab = window.tabs.widget(index)
                    if tab.background_mode is not None:
                        window._show_background_tab(tab)
                        window._hide_background_tab(tab)
        except (OSError, RuntimeError, SystemError, mpv.PropertyUnavailableError) as error:
            self.show_error(f"Could not apply background tab preference: {error}")

    def _save_position(self, tab=None):
        player = tab.player if tab is not None else self.player
        current_file = tab.current_file if tab is not None else self._current_file
        if player is None or not self.settings.resume_enabled or current_file is None:
            return
        if player.mpv.path != str(current_file):
            return
        position = player.mpv.time_pos
        if isinstance(position, (int, float)) and math.isfinite(position) and position >= 0:
            self.settings.set_resume_position(current_file, position)

    def open_file(self, path: str | Path, *, new_tab: bool = False):
        self.banner.hide()
        self.retry_button.hide()
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
            tab = None if new_tab else self._active_tab
            dialog.connected.connect(
                lambda transport: self._open_connected_remote(
                    tab, path, dialog.remote_path, transport, dialog.pool, new_tab=new_tab,
                ),
            )
            dialog.finished.connect(lambda: setattr(self, "_connect_dialog", None))
            dialog.open()
            return
        file = Path(path)
        if not file.is_file():
            self.show_error(f"File not found: {path}")
            return
        if self.player is None:
            self._add_player_tab(file.name)
        self._save_position()
        if self._retry_cancel is not None:
            self._retry_cancel.set()
        self._remote_details = None
        self._failed_position = None
        self._current_file = file.resolve()
        self._active_transport = None
        self._reconnect_attempt = None
        self._cache_paused = False
        self.connection_status.hide()
        start = self.settings.resume_position(self._current_file) if self.settings.resume_enabled else None
        self.player.load(self._current_file, start_position=start)
        self.meta_label.setText("—")
        self._pending_recent = (self.player._uri, str(self._current_file))
        self.location_bar.setText(str(self._current_file))
        self._active_tab.title = file.name
        self._update_tab_status(self._active_tab)
        self._store_active_tab_state()

    def _open_connected_remote(self, tab, uri, remote_path, transport, pool, *, new_tab=False):
        if tab is not None and (not shiboken6.isValid(tab) or self.tabs.indexOf(tab) < 0):
            transport.close()
            return
        if tab is None:
            if new_tab and self.tabs.count() >= 4:
                transport.close()
                self.show_tab_limit(uri)
                return
            self._add_player_tab(Path(remote_path).name)
        elif tab is not self._active_tab:
            self.tabs.setCurrentWidget(tab)
        self._open_remote(uri, remote_path, transport, pool)

    def _open_remote(
        self, uri: str, remote_path: str, transport, pool: SshPool,
        start_position: float | None = None,
    ):
        self._save_position()
        if self._retry_cancel is not None:
            self._retry_cancel.set()
            self._retry_cancel = None
        self._current_file = None
        self._remote_details = (uri, remote_path, pool)
        self._failed_position = None
        self.retry_button.hide()
        self._active_transport = transport
        self._reconnect_attempt = None
        self._cache_paused = False
        self.connection_status.hide()
        self._transports.append(transport)
        self.player.load(
            remote_path, transport=transport, reconnect=pool.reopen_transport,
            start_position=start_position,
        )
        self.meta_label.setText("—")
        self._pending_recent = (self.player._uri, uri)
        self.location_bar.setText(uri)
        self._active_tab.title = Path(remote_path).name
        self._update_tab_status(self._active_tab)
        self._store_active_tab_state()

    def _connection_failed(self, position: float):
        if self._remote_details is None:
            return
        self._failed_position = position
        self.banner.setText(f"Connection lost at {self._clock(position)}")
        self.banner.show()
        self.retry_button.setEnabled(True)
        self.retry_button.show()

    def _show_tab_error(self, tab, message):
        tab.banner_text = message
        tab.banner_visible = True

    def _connection_failed_for_tab(self, tab, position):
        if tab.remote_details is not None:
            tab.failed_position = position
            self._show_tab_error(tab, f"Connection lost at {self._clock(position)}")
            tab.retry_visible = True

    def _retry_remote(self):
        if self._remote_details is None or self._failed_position is None or self._active_transport is None:
            self.show_error("No remote playback is available to retry")
            return
        if self._retry_cancel is not None:
            return
        details = (*self._remote_details, self._failed_position)
        previous = self._active_transport
        tab = self._active_tab
        cancel = threading.Event()
        self._retry_cancel = cancel
        self.retry_button.setEnabled(False)

        def worker():
            try:
                result = details[2].reopen_transport(previous, cancel)
            except Exception as error:  # noqa: BLE001 - surface worker failure on the GUI thread
                result = error
            if self._closing:
                if isinstance(result, paramiko.Transport):
                    result.close()
                return
            self._retry_completed.emit(tab, details, result, cancel)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_remote_retry(self, tab, details, result, cancel):
        if self._closing or tab is not self._active_tab or self._retry_cancel is not cancel or cancel.is_set() or (
            self._remote_details != details[:3]
        ):
            if isinstance(result, paramiko.Transport):
                result.close()
            return
        self._retry_cancel = None
        if isinstance(result, Exception):
            self.show_error(f"Connection lost at {self._clock(details[3])}: Retry failed: {result}")
            self.retry_button.setEnabled(True)
            return
        if not isinstance(result, paramiko.Transport):
            self.show_error("Retry failed: No authenticated SSH transport was returned")
            self.retry_button.setEnabled(True)
            return
        self._open_remote(details[0], details[1], result, details[2], start_position=details[3])

    def _update_connection_status(self):
        if self._active_transport is None:
            self.connection_status.hide()
        elif self._reconnect_attempt is not None:
            self.connection_status.setText(f"Reconnecting… (attempt {self._reconnect_attempt})")
            self.connection_status.show()
        elif self._cache_paused:
            self.connection_status.setText("Buffering…")
            self.connection_status.show()
        else:
            self.connection_status.hide()
        if self._active_tab is not None:
            self._update_tab_status(self._active_tab)

    def _update_tab_status(self, tab):
        if not shiboken6.isValid(tab) or (index := self.tabs.indexOf(tab)) < 0:
            return
        attempt = self._reconnect_attempt if tab is self._active_tab else tab.reconnect_attempt
        paused = self._cache_paused if tab is self._active_tab else tab.cache_paused
        transport = self._active_transport if tab is self._active_tab else tab.active_transport
        status = ""
        if transport is not None:
            if attempt is not None:
                status = f"Reconnecting… (attempt {attempt})"
            elif paused:
                status = "Buffering…"
        self.tabs.setTabText(index, f"{tab.title} · {status}" if status else tab.title)
        self.tabs.setTabToolTip(index, status or tab.title)

    def _remote_reconnecting(self, uri: str, attempt: int, tab=None):
        tab = tab or self._active_tab
        if tab is None or not shiboken6.isValid(tab) or uri != tab.player._uri:
            return
        tab.reconnect_attempt = attempt
        if tab is self._active_tab:
            self._reconnect_attempt = attempt
            self._update_connection_status()
        else:
            self._update_tab_status(tab)

    def _remote_reconnected(self, uri: str, tab=None):
        tab = tab or self._active_tab
        if tab is None or not shiboken6.isValid(tab) or uri != tab.player._uri:
            return
        tab.reconnect_attempt = None
        if tab is self._active_tab:
            self._reconnect_attempt = None
            self._update_connection_status()
        else:
            self._update_tab_status(tab)

    def _remote_retry_failed(self, uri: str, tab=None):
        tab = tab or self._active_tab
        if tab is None or not shiboken6.isValid(tab) or uri != tab.player._uri:
            return
        tab.reconnect_attempt = None
        tab.cache_paused = False
        if tab is self._active_tab:
            self._reconnect_attempt = None
            self._cache_paused = False
            self._update_connection_status()
        else:
            self._update_tab_status(tab)

    def _cache_pause_changed(self, paused, tab=None):
        tab = tab or self._active_tab
        if tab is None or not shiboken6.isValid(tab):
            return
        tab.cache_paused = bool(paused)
        if tab is self._active_tab:
            self._cache_paused = bool(paused)
            self._update_connection_status()
        else:
            self._update_tab_status(tab)

    def _transport_reconnected(self, uri: str, previous, replacement, tab=None):
        tab = tab or self._active_tab
        if tab is None or not shiboken6.isValid(tab) or self.tabs.indexOf(tab) < 0:
            replacement.close()
            return
        transport = self._active_transport if tab is self._active_tab else tab.active_transport
        transports = self._transports if tab is self._active_tab else tab.transports
        if uri == tab.player._uri and transport is replacement:
            return
        if uri != tab.player._uri or transport is not previous:
            replacement.close()
            return
        transports.append(replacement)
        if tab is self._active_tab:
            self._active_transport = replacement
        tab.active_transport = replacement
        transports.remove(previous)
        previous.close()

    def _file_opened(self, tab):
        if tab.player._closed:
            return
        transports = self._transports if tab is self._active_tab else tab.transports
        active_transport = self._active_transport if tab is self._active_tab else tab.active_transport
        for transport in transports[:]:
            if transport is not active_transport:
                transport.close()
                transports.remove(transport)
        pending = self._pending_recent if tab is self._active_tab else tab.pending_recent
        if pending is not None and pending[0] == tab.player._uri:
            try:
                self.settings.add_recent_item(pending[1])
                self._refresh_recent_menu()
            except OSError as error:
                if tab is self._active_tab:
                    self.show_error(str(error))
                else:
                    tab.banner_text, tab.banner_visible = str(error), True
            tab.pending_recent = None
            if tab is self._active_tab:
                self._pending_recent = None

    def _remote_open_failed(self, failed_uri: str, tab=None):
        tab = tab or self._active_tab
        if tab is None or tab.player._closed:
            return
        active = tab is self._active_tab
        pending = self._pending_recent if active else tab.pending_recent
        transport = self._active_transport if active else tab.active_transport
        transports = self._transports if active else tab.transports
        if (
            transport is not None
            and pending is not None
            and pending[0] == failed_uri
        ):
            tab.active_transport = None
            tab.reconnect_attempt = None
            tab.pending_recent = None
            if active:
                self._active_transport = None
                self._reconnect_attempt = None
                self._update_connection_status()
                self._pending_recent = None
            transport.close()
            transports.remove(transport)

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
        tracks = self.player.mpv.track_list if self.player is not None else []
        for menu, kind, prop, cycle in (
            (self.audio_menu, "audio", "aid", self.cycle_audio),
            (self.subtitle_menu, "sub", "sid", self.cycle_sub),
        ):
            menu.clear()
            menu.addAction(cycle)
            menu.addSeparator()
            available = [track for track in tracks if track["type"] == kind]
            cycle.setEnabled(bool(available))
            selected = getattr(self.player.mpv, prop) if self.player is not None else False
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
        if self.player is None:
            self.show_error("Cannot take a snapshot before a file is loaded")
            return
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
        if self._closing:
            super().closeEvent(event)
            return
        self._closing = True
        QApplication.instance().focusChanged.disconnect(self._focus_changed)
        if self._retry_cancel is not None:
            self._retry_cancel.set()
        if self._connect_dialog is not None:
            self._connect_dialog.reject()
        self._store_active_tab_state()
        while self.tabs.count():
            tab = self.tabs.widget(0)
            self._save_position(tab)
            if tab.retry_cancel is not None:
                tab.retry_cancel.set()
            self.tabs.close_tab(0)
        super().closeEvent(event)
        if self.controller is not None and event.isAccepted():
            self.controller.window_closed(self)
