import logging
import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from vplayer import __main__ as entry
from vplayer import __version__
from vplayer.settings import Settings
from vplayer.ui.main_window import MainWindow

MEDIA = Path(__file__).resolve().parent / "media" / "h264_25.mp4"


def test_version_prints_without_starting_qt(capsys, monkeypatch):
    monkeypatch.setattr(entry, "QApplication", lambda argv: pytest.fail("Qt started for --version"))
    with pytest.raises(SystemExit) as exit_status:
        entry.main(["--version"])
    assert exit_status.value.code == 0
    assert capsys.readouterr().out == f"VPlayer {__version__}\n"


@pytest.mark.parametrize("flags", [[], ["--new-window"]])
def test_cli_opens_relative_file_and_reports_missing_file(qtbot, monkeypatch, tmp_path, flags):
    app = QApplication.instance()
    logger = logging.getLogger("vplayer")
    old_handlers = logger.handlers[:]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(entry, "QApplication", lambda argv: app)
    monkeypatch.setattr(entry.QStandardPaths, "writableLocation", lambda location: str(tmp_path))
    monkeypatch.setattr("vplayer.ui.main_window.Settings", lambda: Settings(tmp_path / "settings.ini"))
    relative = os.path.relpath(MEDIA, tmp_path)
    missing = "missing.mp4"

    def exit_after_show(self):
        windows = [w for w in self.topLevelWidgets() if isinstance(w, MainWindow) and w.isVisible()]
        assert len(windows) == 2
        qtbot.waitUntil(lambda: any(w.player.state()["duration"] for w in windows), timeout=10000)
        playing = next(w for w in windows if w.player.state()["duration"])
        failed = next(w for w in windows if w is not playing)
        assert playing.player._uri == str(MEDIA)
        assert failed.banner.isVisible()
        assert "File not found" in failed.banner.text()
        for window in windows:
            window.close()
        return 0

    monkeypatch.setattr(QApplication, "exec", exit_after_show)
    try:
        assert entry.main([*flags, relative, missing]) == 0
    finally:
        for handler in logger.handlers[:]:
            if handler not in old_handlers:
                logger.removeHandler(handler)
                handler.close()
