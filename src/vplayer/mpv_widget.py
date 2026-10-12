"""OpenGL video surface owned by Qt, rendered by libmpv."""

import mpv
import shiboken6
from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QOpenGLContext
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from vplayer.player import Player


class MpvWidget(QOpenGLWidget):
    _frame_ready = Signal()
    ready = Signal()

    def __init__(self, player: Player, parent=None):
        super().__init__(parent)
        self.player = player
        self._render = None
        self._get_proc = mpv.MpvGlGetProcAddressFn(self._get_proc_address)
        self._frame_ready.connect(self._request_frame, Qt.ConnectionType.QueuedConnection)

    @staticmethod
    def _get_proc_address(_context, name):
        context = QOpenGLContext.currentContext()
        return context.getProcAddress(name.decode("ascii")) if context else None

    def initializeGL(self):
        self.context().aboutToBeDestroyed.connect(self.release)
        self._render = mpv.MpvRenderContext(
            self.player.mpv, "opengl",
            opengl_init_params={"get_proc_address": self._get_proc},
        )
        self._render.update_cb = self._frame_ready.emit
        self.ready.emit()

    @Slot()
    def _request_frame(self):
        if self._render and self._render.update():
            self.update()

    def paintGL(self):
        if self._render:
            scale = self.devicePixelRatioF()
            self._render.render(
                flip_y=True,
                opengl_fbo={
                    "fbo": self.defaultFramebufferObject(),
                    "w": round(self.width() * scale),
                    "h": round(self.height() * scale),
                },
            )

    @Slot()
    def release(self):
        if self._render:
            self.makeCurrent()
            # Never reassign update_cb: python-mpv frees the old thunk while mpv's render thread may call it.
            self._render.free()
            self._render = None
            self.doneCurrent()

    def dispose(self):
        if QThread.currentThread() != self.thread():
            raise RuntimeError("Video surface must be disposed on the GUI thread")
        self.release()
        shiboken6.delete(self)
