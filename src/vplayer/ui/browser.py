"""Local media browser dock."""

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QFileSystemModel,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from vplayer import MEDIA_EXTS


class BrowserDock(QDockWidget):
    file_activated = Signal(str)

    def __init__(self, parent=None, root: Path | None = None):
        super().__init__("Browser", parent)
        content = QWidget(self)
        layout = QVBoxLayout(content)
        self.all_files = QCheckBox("All files", content)
        self.all_files.setAccessibleName("Show all files")
        layout.addWidget(self.all_files)

        self.model = QFileSystemModel(self)
        self.model.setNameFilters([f"*{ext}" for ext in MEDIA_EXTS])
        self.model.setNameFilterDisables(False)
        self.tree = QTreeView(content)
        self.tree.setAccessibleName("Local files")
        self.tree.setModel(self.model)
        directory = str(root or Path.home())
        self.tree.setRootIndex(self.model.setRootPath(directory))
        self.tree.activated.connect(self._activate)
        layout.addWidget(self.tree)
        self.setWidget(content)
        self.all_files.toggled.connect(
            lambda show_all: self.model.setNameFilters(["*"] if show_all else [f"*{ext}" for ext in MEDIA_EXTS])
        )

    def _activate(self, index):
        if self.model.isDir(index):
            self.tree.setRootIndex(index)
        else:
            self.file_activated.emit(str(Path(self.model.filePath(index))))
