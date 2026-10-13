import logging
import warnings
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QApplication

from vplayer.player import Player

MEDIA = Path(__file__).resolve().parent / "media" / "h264_25.mp4"


def test_load_and_observe_on_gui_thread(qtbot):
    player = Player(video_output="null")
    threads = []
    player.file_loaded.connect(
        lambda: threads.append(QThread.currentThread()),
        Qt.ConnectionType.DirectConnection,
    )
    try:
        assert player.mpv["cache-on-disk"] is False
        assert player.mpv["hwdec"] in ("auto-safe", ["auto-safe"])
        with qtbot.waitSignal(player.file_loaded, timeout=10000):
            player.load(MEDIA)
        assert threads == [QApplication.instance().thread()]
        assert player.state()["duration"] > 0
        player.play_pause()
        qtbot.waitUntil(lambda: player.state()["pause"] is True)
        player.play_pause()
        qtbot.waitUntil(lambda: player.state()["pause"] is False)
    finally:
        player.close()


def test_software_decoding_mode_survives_probe_reload(qtbot, caplog):
    player = Player(video_output="null", hwdec="no")
    errors = []
    player.error.connect(errors.append)
    try:
        with caplog.at_level(logging.INFO, logger="vplayer.player"):
            with qtbot.waitSignal(player.file_loaded, timeout=10000):
                player.load(MEDIA)
            qtbot.waitUntil(lambda: "hwdec-current: no" in caplog.text, timeout=5000)
        assert player.mpv["hwdec"] in ("no", ["no"])
        assert player.mpv.hwdec_current == "no"
        assert not errors
    finally:
        player.close()


def test_unavailable_hardware_decoder_falls_back_without_error(qtbot):
    player = Player(video_output="null")
    errors = []
    player.error.connect(errors.append)
    try:
        with qtbot.waitSignal(player.file_loaded, timeout=10000):
            player.mpv.loadfile(str(MEDIA.parent / "matrix_h264_mp4.mp4"), hwdec="vaapi")
        player.mpv.pause = False
        qtbot.waitUntil(lambda: player.mpv.eof_reached, timeout=10000)
        assert player.mpv.hwdec_current == "no"
        assert not errors
    finally:
        player.close()


def test_hardware_decoder_mode_rejects_unsupported_configuration():
    with pytest.raises(ValueError, match="Hardware decoding"):
        Player(hwdec="vaapi")


def test_close_during_probe_reload_does_not_touch_freed_handle(qtbot):
    # The probe reload runs on mpv's event thread; close() used to free the handle under it.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for delay_ms in range(0, 60, 3):
            player = Player(video_output="null")
            player.load(MEDIA)
            qtbot.wait(delay_ms)
            player.close()
            assert player.wait_closed(10)
    assert not [str(w.message) for w in caught if "event loop" in str(w.message)]


def test_missing_file_emits_error_without_loading(qtbot, tmp_path):
    player = Player(video_output="null")
    try:
        with qtbot.waitSignal(player.error):
            player.load(tmp_path / "missing.mp4")
        assert player.state()["duration"] is None
    finally:
        player.close()


def test_unplayable_file_reports_mpv_error(qtbot, tmp_path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")
    player = Player(video_output="null")
    try:
        with qtbot.waitSignal(player.error, timeout=5000):
            player.load(broken)
    finally:
        player.close()


def test_seek_clamps_to_first_and_last_frame(qtbot):
    player = Player(video_output="null")
    try:
        with qtbot.waitSignal(player.error):
            player.seek(1)
        with qtbot.waitSignal(player.file_loaded, timeout=10000):
            player.mpv.pause = True
            player.load(MEDIA)
        last_frame = player.state()["duration"] - 1 / player.mpv.container_fps
        player.seek(1000)
        qtbot.waitUntil(lambda: abs(player.state()["time-pos"] - last_frame) < 0.05)
        player.seek(-1000, relative=True)
        qtbot.waitUntil(lambda: player.state()["time-pos"] < 0.05)
        with qtbot.waitSignal(player.error):
            player.seek(float("nan"))
    finally:
        player.close()


def test_volume_is_bounded_and_mute_keeps_level():
    player = Player(video_output="null")
    try:
        player.mpv.volume = 40
        with patch.object(player.mpv, "show_text") as osd:
            player.adjust_volume(5)
            assert player.mpv.volume == 45
            osd.assert_called_with("Volume: 45%", 1000)
            player.toggle_mute()
            assert player.mpv.mute is True
            assert player.mpv.volume == 45
            osd.assert_called_with("Muted", 1000)
            player.toggle_mute()
            assert player.mpv.mute is False
            assert player.mpv.volume == 45
            player.adjust_volume(1000)
            assert player.mpv.volume == 100
            player.adjust_volume(-1000)
            assert player.mpv.volume == 0
    finally:
        player.close()


def test_close_unregisters_mpv_callbacks():
    player = Player(video_output="null")
    assert player.mpv._event_callbacks
    assert all(player.mpv._property_handlers.values())
    player.close()
    player.close()
    assert not player.mpv._event_callbacks
    assert not any(player.mpv._property_handlers.values())
    assert player.wait_closed(10)
