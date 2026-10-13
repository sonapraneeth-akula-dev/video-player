import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from vplayer.app import AppController, parse_open_request

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
