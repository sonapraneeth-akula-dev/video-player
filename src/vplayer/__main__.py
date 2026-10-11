"""Application entry point."""

import locale
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

from vplayer import APP_NAME


def main() -> int:
    if sys.platform == "win32":
        vendor = Path(__file__).resolve().parents[2] / "vendor"
        os.environ["PATH"] = str(vendor) + os.pathsep + os.environ["PATH"]

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    locale.setlocale(locale.LC_NUMERIC, "C")
    log_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("vplayer")
    logger.setLevel(logging.INFO)
    logger.addHandler(RotatingFileHandler(log_dir / "vplayer.log", maxBytes=1_000_000, backupCount=3))

    from vplayer.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

