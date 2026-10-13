import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import psutil
import pytest
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication

from vplayer.app import AppController, parse_open_request
from vplayer.single_instance import SingleInstance, open_message

MEDIA = Path(__file__).parent / "media" / "h264_25.mp4"


def message(*items, new_window=False):
    return json.dumps({"v": 1, "new_window": new_window, "items": list(items)}).encode()


@pytest.mark.parametrize(
    "payload",
    (
        b"{",
        b"\xff",
        b"null",
        b"[]",
        b'{"v":2,"new_window":false,"items":[]}',
        b'{"v":true,"new_window":false,"items":[]}',
        b'{"v":1,"new_window":0,"items":[]}',
        b'{"v":1,"new_window":false,"items":"file"}',
        message("relative.mp4"),
        message("sftp://"),
        message("sftp://[invalid/video.mp4"),
        message(5),
        message(""),
        pytest.param(b"x" * 65537, id="oversized"),
    ),
)
def test_malformed_or_oversized_request_is_dropped_and_logged(payload, caplog):
    with caplog.at_level("WARNING", logger="vplayer"):
        assert parse_open_request(payload) is None
    assert "Ignoring" in caplog.text
    assert "invalid/video.mp4" not in caplog.text


def test_receiver_accepts_absolute_paths_sftp_uris_and_exact_limit():
    assert parse_open_request(message(str(MEDIA.resolve()), "sftp://user@host/video.mp4")) == {
        "v": 1, "new_window": False,
        "items": [str(MEDIA.resolve()), "sftp://user@host/video.mp4"],
    }
    padded = message().ljust(65536, b" ")
    assert parse_open_request(padded) == {"v": 1, "new_window": False, "items": []}


def test_receiver_uses_focused_window_then_opens_overflow_elsewhere(qtbot):
    controller = AppController(QApplication.instance())
    first = controller.new_window()
    second = controller.new_window()
    qtbot.addWidget(first)
    qtbot.addWidget(second)
    try:
        first.activateWindow()
        qtbot.waitUntil(first.isActiveWindow)
        assert controller.last_used_window is first
        files = [str(MEDIA.resolve())] * 5
        assert controller.receive_open_request(message(*files))
        assert first.tabs.count() == 4 and second.tabs.count() == 0
        overflow = controller.windows[-1]
        qtbot.addWidget(overflow)
        assert overflow is not first and overflow is not second
        assert overflow.tabs.count() == 1 and overflow.player._uri == files[0]
        assert overflow.isVisible()
        qtbot.waitUntil(lambda: controller.last_used_window is overflow)
        assert controller.receive_open_request(message(str(MEDIA.resolve()), new_window=True))
        explicit = controller.windows[-1]
        qtbot.addWidget(explicit)
        assert explicit.tabs.count() == 1 and explicit.player._uri == files[0]
    finally:
        for window in controller.windows[:]:
            window.close()


def test_receiver_rejects_invalid_message_without_creating_window(qtbot, caplog, tmp_path):
    controller = AppController(QApplication.instance())
    try:
        with caplog.at_level("WARNING", logger="vplayer"):
            assert not controller.receive_open_request(message("sftp://"))
        assert controller.windows == []
        missing = tmp_path / "missing.mp4"
        assert controller.receive_open_request(message(str(missing), str(MEDIA.resolve())))
        window = controller.windows[0]
        qtbot.addWidget(window)
        assert window.tabs.count() == 1 and window.player._uri == str(MEDIA.resolve())
        assert window.statusBar().currentMessage() == "Could not open 1 file(s)"
        assert not controller.receive_open_request(b"bad json")
        assert controller.windows == [window] and window.tabs.count() == 1
    finally:
        for window in controller.windows[:]:
            window.close()


def test_sender_resolves_local_paths_before_forwarding(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = json.loads(open_message(["video.mp4", "sftp://user@host/video.mp4"], new_window=True))
    assert payload == {
        "v": 1, "new_window": True,
        "items": [str(tmp_path / "video.mp4"), "sftp://user@host/video.mp4"],
    }
    with pytest.raises(ValueError, match="64 KB"):
        open_message(["sftp://host/" + "x" * 65536])


def test_local_server_acknowledges_one_valid_request(qtbot):
    receiver = Mock()
    receiver.receive_open_request.return_value = True
    name = f"vplayer-test-{uuid4().hex}"
    server = SingleInstance(receiver, name)
    assert server.start(message())
    try:
        script = (
            "import sys; from vplayer.single_instance import SingleInstance; "
            "raise SystemExit(1 if SingleInstance(None, sys.argv[1]).start(sys.argv[2].encode()) else 0)"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", script, name, message(str(MEDIA.resolve())).decode()],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            qtbot.waitUntil(lambda: child.poll() is not None, timeout=10000)
            assert child.returncode == 0, child.communicate(timeout=2)[1]
        finally:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=10)
        receiver.receive_open_request.assert_called_once_with(message(str(MEDIA.resolve())))
    finally:
        server.close()


def test_local_server_rejects_oversized_message(qtbot, caplog):
    receiver = Mock()
    name = f"vplayer-test-{uuid4().hex}"
    server = SingleInstance(receiver, name)
    assert server.start(message())
    client = QLocalSocket()
    try:
        client.connectToServer(name)
        qtbot.waitUntil(lambda: client.state() == QLocalSocket.LocalSocketState.ConnectedState)
        client.write(b"x" * 65537 + b"\n")
        client.flush()
        with caplog.at_level("WARNING", logger="vplayer"):
            qtbot.waitUntil(lambda: client.bytesAvailable() > 0, timeout=10000)
        assert bytes(client.readAll()) == b"error\n"
        receiver.receive_open_request.assert_not_called()
        assert "oversized" in caplog.text
    finally:
        client.abort()
        server.close()


def test_five_simultaneous_cli_launches_share_one_playing_primary(tmp_path, monkeypatch):
    name = f"vplayer-test-{uuid4().hex}"
    snapshot = tmp_path / "snapshot.json"
    files = []
    for index in range(5):
        target = tmp_path / f"video-{index}.mp4"
        target.write_bytes(MEDIA.read_bytes())
        files.append(str(target))

    script = """
import json
import os
import sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from vplayer import __main__ as entry, single_instance
from vplayer.settings import Settings
from vplayer.ui import main_window

name, snapshot, media = sys.argv[1:]
single_instance.instance_name = lambda: name
entry.QStandardPaths.writableLocation = staticmethod(lambda _location: str(Path(snapshot).parent))
main_window.Settings = lambda: Settings(Path(snapshot).with_suffix(".ini"))
original_exec = QApplication.exec

def monitored_exec(app):
    timer = QTimer()
    def check():
        windows = [w for w in app.topLevelWidgets() if isinstance(w, main_window.MainWindow) and w.isVisible()]
        opened = [
            tab.player._uri for w in windows for i in range(w.tabs.count())
            if (tab := w.tabs.widget(i)).player.mpv.duration is not None
        ]
        if len(opened) == 5:
            Path(snapshot).write_text(json.dumps({"pid": os.getpid(), "items": opened, "windows": len(windows)}))
            timer.stop()
    timer.timeout.connect(check)
    timer.start(50)
    return original_exec()

QApplication.exec = monitored_exec
raise SystemExit(entry.main([media]))
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, name, str(snapshot), file],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=os.environ.copy(),
        )
        for file in files
    ]
    try:
        deadline = time.monotonic() + 35
        while not snapshot.exists() and time.monotonic() < deadline:
            if all(process.poll() is not None for process in processes):
                break
            time.sleep(0.1)
        failures = [
            (process.pid, process.returncode, process.communicate(timeout=2)[1][-4000:])
            for process in processes if process.poll() not in (None, 0)
        ]
        assert snapshot.exists(), failures
        state = json.loads(snapshot.read_text())
        assert sorted(state["items"]) == sorted(files)
        assert state["windows"] == 2
        assert sum(process.poll() is None for process in processes) == 1
        assert all(process.returncode == 0 for process in processes if process.poll() is not None)
    finally:
        for process in processes:
            if process.poll() is None:
                for child in reversed(psutil.Process(process.pid).children(recursive=True)):
                    child.terminate()
                process.terminate()
            process.communicate(timeout=10)
        monkeypatch.setattr(
            "vplayer.single_instance.QStandardPaths.writableLocation",
            lambda _location: str(tmp_path),
        )
        recovery = SingleInstance(None, name)
        assert recovery.start(message())
        recovery.close()
