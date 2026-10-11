"""Local media browser and lazy remote directory model."""

import posixpath
import stat
from dataclasses import dataclass
from pathlib import Path

import paramiko
from PySide6.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QFileSystemModel,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from vplayer import MEDIA_EXTS

_ROOT_INDEX = QModelIndex()


class BrowserDock(QDockWidget):
    file_activated = Signal(str)

    def __init__(self, parent=None, root: Path | None = None):
        super().__init__("Browser", parent)
        self.setAccessibleName("Local browser")
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


@dataclass
class _RemoteNode:
    name: str
    path: str
    directory: bool
    parent: "_RemoteNode | None" = None
    children: list["_RemoteNode"] | None = None
    loading: bool = False
    error: bool = False


class SftpDirModel(QAbstractItemModel):
    _listed = Signal(object, object, object)

    def __init__(self, sftp: paramiko.SFTPClient, root: str = "/", parent=None):
        super().__init__(parent)
        if not isinstance(root, str) or not root.startswith("/") or "\x00" in root:
            raise ValueError("Remote browser root must be an absolute SFTP path")
        self.sftp = sftp
        self.root = _RemoteNode("", posixpath.normpath(root), True)
        self.show_all = False
        self.workers = QThreadPool(self)
        self._listed.connect(self._receive_listing)

    def _visible(self, node: _RemoteNode) -> list[_RemoteNode]:
        return [
            child for child in node.children or []
            if child.directory or child.error or self.show_all
            or posixpath.splitext(child.name)[1].lower() in MEDIA_EXTS
        ]

    def _node(self, index: QModelIndex) -> _RemoteNode:
        return index.internalPointer() if index.isValid() else self.root

    def index(self, row: int, column: int, parent: QModelIndex = _ROOT_INDEX) -> QModelIndex:
        if row < 0 or column != 0 or parent.column() > 0:
            return QModelIndex()
        children = self._visible(self._node(parent))
        return self.createIndex(row, column, children[row]) if row < len(children) else QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        parent = self._node(index).parent
        if parent is None or parent is self.root:
            return QModelIndex()
        grandparent = parent.parent
        return self.createIndex(self._visible(grandparent).index(parent), 0, parent)

    def rowCount(self, parent: QModelIndex = _ROOT_INDEX) -> int:
        return len(self._visible(self._node(parent))) if parent.column() <= 0 else 0

    def columnCount(self, parent: QModelIndex = _ROOT_INDEX) -> int:
        return 1

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node = self._node(index)
        if role == Qt.ItemDataRole.DisplayRole:
            return node.name
        if role == Qt.ItemDataRole.UserRole:
            return node.path
        if role == Qt.ItemDataRole.UserRole + 1:
            return node.directory
        if role == Qt.ItemDataRole.ToolTipRole and node.error:
            return node.name
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if index.isValid() and self._node(index).error:
            return Qt.ItemFlag.NoItemFlags
        return super().flags(index)

    def hasChildren(self, parent: QModelIndex = _ROOT_INDEX) -> bool:
        node = self._node(parent)
        return node.directory and (node.children is None or bool(self._visible(node)))

    def canFetchMore(self, parent: QModelIndex) -> bool:
        node = self._node(parent)
        return node.directory and node.children is None and not node.loading

    def fetchMore(self, parent: QModelIndex) -> None:
        if not self.canFetchMore(parent):
            return
        node = self._node(parent)
        node.loading = True

        def list_directory():
            try:
                entries = self.sftp.listdir_attr(node.path)
            except UnicodeError:
                self._listed.emit(node, None, "filename not UTF-8")
            except (OSError, EOFError, paramiko.SSHException) as error:
                self._listed.emit(node, None, str(error) or type(error).__name__)
            else:
                self._listed.emit(node, entries, None)

        self.workers.start(list_directory)

    @Slot(object, object, object)
    def _receive_listing(self, node: _RemoteNode, entries: list[paramiko.SFTPAttributes] | None, error: str | None):
        if error is not None:
            children = [_RemoteNode(f"Can't list: {error}", node.path, False, node, error=True)]
        else:
            assert entries is not None
            children = []
            for entry in entries:
                name = entry.filename
                if not isinstance(name, str) or not name or name in (".", "..") or "/" in name or "\x00" in name:
                    children.append(_RemoteNode("Can't list: invalid filename", node.path, False, node, error=True))
                    continue
                if not isinstance(entry.st_mode, int):
                    children.append(_RemoteNode("Can't list: missing file type", node.path, False, node, error=True))
                    continue
                children.append(_RemoteNode(
                    name, posixpath.join(node.path, name), stat.S_ISDIR(entry.st_mode), node,
                ))
            children.sort(key=lambda child: (not child.directory, child.name.casefold()))
        visible = sum(
            child.directory or child.error or self.show_all
            or posixpath.splitext(child.name)[1].lower() in MEDIA_EXTS
            for child in children
        )
        parent = self._index_for_node(node)
        if visible:
            self.beginInsertRows(parent, 0, visible - 1)
        node.children = children
        node.loading = False
        if visible:
            self.endInsertRows()
        elif parent.isValid():
            self.dataChanged.emit(parent, parent)

    def _index_for_node(self, node: _RemoteNode) -> QModelIndex:
        if node is self.root:
            return QModelIndex()
        return self.createIndex(self._visible(node.parent).index(node), 0, node)

    def set_show_all(self, show_all: bool) -> None:
        if self.show_all != show_all:
            self.beginResetModel()
            self.show_all = show_all
            self.endResetModel()
