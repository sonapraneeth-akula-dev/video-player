from itertools import pairwise
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from vplayer.settings import Settings
from vplayer.ui.main_window import MainWindow, SeekBar

MEDIA = Path(__file__).resolve().parent / "media" / "h264_25.mp4"


def test_seek_bar_paints_both_loop_markers(qtbot):
    bar = SeekBar()
    qtbot.addWidget(bar)
    bar.resize(400, 30)
    bar.setEnabled(True)
    bar.show()
    before = bar.grab().toImage().bits().tobytes()
    bar.set_loop_points(0.25, "no", 1.0)
    with_start = bar.grab().toImage().bits().tobytes()
    bar.set_loop_points(0.25, 0.75, 1.0)
    with_both = bar.grab().toImage().bits().tobytes()
    assert before != with_start != with_both
    assert (bar.loop_a, bar.loop_b) == (0.25, 0.75)
    assert bar.accessibleDescription() == "A: 0.250s, B: 0.750s"
    bar.set_loop_points("no", "no", 1.0)
    assert (bar.loop_a, bar.loop_b) == (None, None)


def test_ab_loop_actions_repeat_segment_clear_and_reset_on_new_file(qtbot, tmp_path):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    window._add_player_tab("Video")
    qtbot.addWidget(window)
    window.show()
    try:
        actions = {action.objectName(): action for action in window.playback_menu.actions()}
        for name, shortcut in (("ab_set_a", "Ctrl+Alt+1"), ("ab_set_b", "Ctrl+Alt+2"), ("ab_clear", "Ctrl+Alt+0")):
            assert actions[name].shortcut().toString() == shortcut
        with qtbot.waitSignal(window.player.error) as error:
            actions["ab_set_a"].trigger()
        assert "before a file" in error.args[0]
        with qtbot.waitSignal(window.player.error) as error:
            actions["ab_set_b"].trigger()
        assert "before a file" in error.args[0]
        qtbot.waitUntil(lambda: window.video._render is not None, timeout=10000)
        window.player.mpv.pause = True
        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            window.open_file(MEDIA)
        window.player.mpv.seek(1, reference="absolute", precision="exact")
        qtbot.waitUntil(lambda: abs((window.player.mpv.time_pos or 0) - 1) < 0.05, timeout=10000)
        actions["ab_set_a"].trigger()
        assert window.player.mpv.ab_loop_a == 1
        window.player.mpv.seek(2, reference="absolute", precision="exact")
        qtbot.waitUntil(lambda: abs((window.player.mpv.time_pos or 0) - 2) < 0.05, timeout=10000)
        actions["ab_set_b"].trigger()
        assert window.player.mpv.ab_loop_b == 2
        assert window.seek_bar.loop_a == 1
        assert window.seek_bar.loop_b == 2

        positions = []
        window.player.position.connect(lambda position: positions.append(position) if position is not None else None)
        window.player.mpv.seek(1.1, reference="absolute", precision="exact")
        window.player.mpv.pause = False
        qtbot.waitUntil(
            lambda: any(
                first >= 1.8 and second <= 1.3
                for first, second in pairwise(positions)
            ),
            timeout=10000,
        )

        window.activateWindow()
        qtbot.waitUntil(window.isActiveWindow)
        window.video.setFocus()
        qtbot.waitUntil(window.video.hasFocus)
        QTest.keyClick(window.video, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        assert (window.player.mpv.ab_loop_a, window.player.mpv.ab_loop_b) == ("no", "no")
        assert (window.seek_bar.loop_a, window.seek_bar.loop_b) == (None, None)
        qtbot.waitUntil(lambda: (window.player.mpv.time_pos or 0) > 2.5, timeout=10000)

        actions["ab_set_a"].trigger()
        assert window.seek_bar.loop_a is not None
        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            window.open_file(MEDIA)
        assert (window.player.mpv.ab_loop_a, window.player.mpv.ab_loop_b) == ("no", "no")
        assert (window.seek_bar.loop_a, window.seek_bar.loop_b) == (None, None)
    finally:
        window.close()
