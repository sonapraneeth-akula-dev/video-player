from pathlib import Path

from PySide6.QtGui import QColor

from vplayer.mpv_widget import MpvWidget
from vplayer.player import Player

MEDIA = Path(__file__).resolve().parent / "media" / "h264_25.mp4"


def test_rendered_frame_has_letterbox_and_releases_context(qtbot):
    player = Player()
    widget = MpvWidget(player)
    qtbot.addWidget(widget)
    widget.resize(400, 400)
    widget.show()
    try:
        qtbot.waitUntil(lambda: widget._render is not None, timeout=10000)
        with qtbot.waitSignal(player.file_loaded, timeout=10000):
            player.load(MEDIA)
        qtbot.waitUntil(
            lambda: widget.grabFramebuffer().pixelColor(200, 200).red() > 35,
            timeout=10000,
        )
        image = widget.grabFramebuffer()
        assert image.pixelColor(200, 200).red() > 35
        assert image.pixelColor(200, 20) == QColor("black")
    finally:
        widget.release()
        player.close()
        widget.close()

