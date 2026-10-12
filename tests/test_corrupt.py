import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer

from vplayer.settings import Settings
from vplayer.ui.main_window import MainWindow

CORPUS = Path(__file__).resolve().parent / "media"


def test_corrupt_corpus_keeps_process_and_event_loop_alive():
    environment = os.environ.copy()
    environment["VPLAYER_CORRUPT_WORKER"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", f"{Path(__file__).resolve()}::test_corrupt_worker"],
        env=environment, capture_output=True, text=True, timeout=400, check=False,
    )
    assert result.returncode == 0, (
        f"Corrupt corpus worker exited {result.returncode}:\n"
        f"{result.stdout[-4000:]}\n{result.stderr[-2000:]}"
    )


def test_undecodable_video_with_hwdec_keeps_core_responsive():
    # Both hwdec and software fail to open this HEVC stream; libmpv used to retry forever and block every API call.
    script = (
        "import time; from PySide6.QtWidgets import QApplication; from vplayer.player import Player\n"
        "app = QApplication([]); player = Player(video_output='null'); player.mpv.ao = 'null'\n"
        f"player.load({str(CORPUS / 'corrupt_16_flipped.mkv')!r})\n"
        "deadline = time.monotonic() + 3\n"
        "while time.monotonic() < deadline: app.processEvents(); player.state(); time.sleep(0.05)\n"
        "player.close()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], env=os.environ.copy(), capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]


@pytest.mark.skipif(os.environ.get("VPLAYER_CORRUPT_WORKER") != "1", reason="run in a separate process")
def test_corrupt_worker(qtbot, tmp_path):
    files = sorted(CORPUS.glob("corrupt_*"))
    assert len(files) >= 50
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    window.player.mpv.ao = "null"
    window.show()
    errors = []
    window.player.error.connect(errors.append)
    window.player.file_loaded.connect(lambda: setattr(window.player.mpv, "pause", False))
    heartbeats = []
    timer = QTimer(window)
    timer.timeout.connect(lambda: heartbeats.append(time.monotonic()))
    timer.start(100)
    try:
        qtbot.waitUntil(lambda: window.video._render is not None, timeout=10000)
        for path in files:
            print(path.name, flush=True)
            errors.clear()
            before = len(heartbeats)
            started = time.monotonic()
            window.open_file(path)
            qtbot.waitUntil(lambda before=before: len(heartbeats) > before, timeout=3000)
            assert time.monotonic() - started < 5, f"GUI stalled opening {path.name}"
            deadline = started + 5
            while time.monotonic() < deadline and not errors and not window.player.mpv.eof_reached:
                qtbot.wait(50)
            assert len(heartbeats) > before, f"GUI event loop stopped on {path.name}"
    finally:
        window.close()
