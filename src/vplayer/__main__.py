"""Application entry point."""

import argparse
import locale
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtWidgets import QApplication

from vplayer import APP_NAME, __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vplayer")
    parser.add_argument("files", metavar="FILE", nargs="*")
    parser.add_argument("--new-window", action="store_true")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args = parser.parse_args(argv)

    if sys.platform == "win32":
        vendor = Path(__file__).resolve().parents[2] / "vendor"
        os.environ["PATH"] = str(vendor) + os.pathsep + os.environ["PATH"]

    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    locale.setlocale(locale.LC_NUMERIC, "C")
    log_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("vplayer")
    logger.setLevel(logging.INFO)
    logger.addHandler(RotatingFileHandler(log_dir / "vplayer.log", maxBytes=1_000_000, backupCount=3))

    from vplayer.ui.main_window import MainWindow

    windows = []
    for file in args.files or [None]:
        window = MainWindow()
        if file is not None:
            path = file if file.startswith("sftp://") else os.path.abspath(file)
            window.video.ready.connect(
                lambda window=window, path=path: window.open_file(path),
                Qt.ConnectionType.SingleShotConnection,
            )
        window.show()
        windows.append(window)
    # ponytail: until tabs/IPC exist, separate windows keep every CLI file reachable.
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
