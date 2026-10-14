"""Application entry point."""

import argparse
import ctypes
import ctypes.util
import locale
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

import shiboken6
from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QStandardPaths,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtWidgets import QApplication

from vplayer import APP_NAME, __version__


class _ErrorReporter(QObject):
    message = Signal(str, object)

    def __init__(self, windows):
        super().__init__()
        self.windows = windows
        self.message.connect(self._show, Qt.ConnectionType.QueuedConnection)

    def report(self, message):
        active = None
        if QThread.currentThread() == self.thread():
            active = QApplication.activeWindow()
            if active is None:
                active = next(
                    (window for window in reversed(self.windows) if shiboken6.isValid(window) and window.isVisible()),
                    None,
                )
        self.message.emit(message, active)

    @Slot(str, object)
    def _show(self, message, origin):
        active = origin if origin is not None and shiboken6.isValid(origin) else QApplication.activeWindow()
        visible = [window for window in self.windows if shiboken6.isValid(window) and window.isVisible()]
        target = next(
            (window for window in visible if active is window or (active and window.isAncestorOf(active))),
            visible[-1] if visible else None,
        )
        if target is not None:
            target.show_error(message)


def _install_exception_handlers(windows):
    reporter = _ErrorReporter(windows)
    previous_sys = sys.excepthook
    previous_thread = threading.excepthook
    log = logging.getLogger("vplayer")

    def report(exc_type, error, traceback):
        log.error("Unhandled application exception", exc_info=(exc_type, error, traceback))
        reporter.report(f"Unexpected error: {exc_type.__name__}: {error}")

    sys.excepthook = report
    threading.excepthook = lambda args: report(args.exc_type, args.exc_value, args.exc_traceback)

    def restore():
        sys.excepthook = previous_sys
        threading.excepthook = previous_thread

    return restore


def _attach_parent_console() -> None:
    if sys.platform != "win32" or (sys.stdout is not None and sys.stderr is not None):
        return
    attach = ctypes.WinDLL("kernel32", use_last_error=True).AttachConsole
    attach.argtypes = [ctypes.c_uint32]
    attach.restype = ctypes.c_int
    if not attach(0xFFFFFFFF):
        error = ctypes.get_last_error()
        if error == 6:
            return
        if error != 5:
            raise ctypes.WinError(error)
    if sys.stdout is None:
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115


def _probe_codec(app: QApplication, window, kind: str) -> int:
    loaded = False
    completed = False
    eof_seen = False
    errors = []
    audio_seen = False
    frame_seen = False
    window.player.mpv.ao = "null"
    window.player.mpv.pause = True

    def file_loaded():
        nonlocal loaded, audio_seen
        loaded = True
        if window.player.mpv.audio_params is not None:
            audio_seen = True
        window.player.mpv.pause = False

    window.player.file_loaded.connect(file_loaded)
    window.player.error.connect(errors.append)
    timer = QTimer(window)

    def check():
        nonlocal audio_seen, frame_seen, completed, eof_seen
        if errors:
            app.exit(1)
            return
        if not loaded:
            return
        if window.player.mpv.audio_params is not None:
            audio_seen = True
        if kind == "video" and not frame_seen:
            image = window.video.grabFramebuffer()
            if not image.isNull() and image.pixelColor(image.width() // 2, image.height() // 2).red() > 35:
                frame_seen = True
        if window.player.mpv.eof_reached:
            eof_seen = True
            timer.stop()
            completed = audio_seen and (kind == "audio" or frame_seen)
            QTimer.singleShot(100, lambda: app.exit(0 if completed and not errors else 1))

    timer.timeout.connect(check)
    timer.start(50)
    QTimer.singleShot(30000, lambda: app.exit(1))
    window.show()
    status = app.exec()
    window.close()
    if status or not completed or errors:
        logging.getLogger("vplayer").error(
            "Codec probe failed: kind=%s loaded=%s audio=%s frame=%s eof=%s errors=%s",
            kind, loaded, audio_seen, frame_seen, eof_seen, errors,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    _attach_parent_console()
    parser = argparse.ArgumentParser(prog="vplayer")
    parser.add_argument("files", metavar="FILE", nargs="*")
    parser.add_argument("--new-window", action="store_true")
    parser.add_argument("--install", action="store_true", help="Install VPlayer for the current user")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall per-user VPlayer installation")
    parser.add_argument("--default", action="store_true", help="Register as default video handler with --install")
    parser.add_argument("--codec-probe", choices=("video", "audio"), help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args = parser.parse_args(argv)
    if args.install and args.uninstall:
        parser.error("--install and --uninstall cannot be used together")
    if args.default and not args.install:
        parser.error("--default requires --install")
    if (args.install or args.uninstall) and args.files:
        parser.error("--install/--uninstall do not accept FILE arguments")
    if args.install or args.uninstall:
        from vplayer.installer import run_install, run_uninstall

        return run_install(set_default=args.default) if args.install else run_uninstall()
    if args.codec_probe and len(args.files) != 1:
        parser.error("--codec-probe requires exactly one FILE")

    libdir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2] / "vendor"))
    if sys.platform == "win32":
        os.environ["PATH"] = str(libdir) + os.pathsep + os.environ["PATH"]
    elif getattr(sys, "frozen", False):
        # python-mpv only asks find_library, which never searches the bundle.
        bundled = str(next(libdir.glob("libmpv*")))
        find = ctypes.util.find_library
        ctypes.util.find_library = lambda name: bundled if name == "mpv" else find(name)

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    locale.setlocale(locale.LC_NUMERIC, "C")
    log_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("vplayer")
    logger.setLevel(logging.INFO)
    logger.addHandler(RotatingFileHandler(log_dir / "vplayer.log", maxBytes=1_000_000, backupCount=3))

    from vplayer.app import AppController
    from vplayer.single_instance import SingleInstance, open_message

    controller = AppController(app)
    instance = None
    if not args.codec_probe:
        try:
            instance = SingleInstance(controller)
            payload = open_message(args.files, new_window=args.new_window)
            if not instance.start(payload):
                return 0
            if not controller.receive_open_request(payload):
                raise RuntimeError("Could not open initial request")
        except (OSError, RuntimeError, ValueError) as error:
            if instance is not None:
                instance.close()
            logger.error("Could not route external open request: %s", error)
            if sys.stderr is not None:
                print(f"VPlayer: {error}", file=sys.stderr)
            return 1
    restore = _install_exception_handlers(controller.windows)
    try:
        if args.codec_probe:
            file = args.files[0]
            window = controller.new_window(show=False)
            path = os.path.abspath(file)
            tab = window._add_player_tab(Path(path).name)
            tab.video.ready.connect(
                lambda window=window, path=path: window.open_file(path),
                Qt.ConnectionType.SingleShotConnection,
            )
            return _probe_codec(app, window, args.codec_probe)
        return app.exec()
    finally:
        restore()
        if instance is not None:
            instance.close()


if __name__ == "__main__":
    sys.exit(main())
