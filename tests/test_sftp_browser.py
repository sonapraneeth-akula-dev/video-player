import stat
from pathlib import Path
from types import SimpleNamespace

import paramiko
import pytest
from PySide6.QtCore import QModelIndex, Qt, QThread
from PySide6.QtWidgets import QApplication, QTreeView

from vplayer.sftp import KnownHosts
from vplayer.ui.browser import SftpDirModel

ROOT_INDEX = QModelIndex()


def entry(name, *, directory=False):
    mode = stat.S_IFDIR if directory else stat.S_IFREG
    return SimpleNamespace(filename=name, st_mode=mode)


class FakeSftpClient:
    def __init__(self):
        self.calls = []
        self.threads = []
        self.directories = {
            "/media": [entry("clips", directory=True), entry("denied", directory=True),
                       entry("missing", directory=True), entry("movie.MP4"), entry("notes.txt")],
            "/media/clips": [entry("inside.mkv")],
        }

    def listdir_attr(self, path):
        self.calls.append(path)
        self.threads.append(QThread.currentThread())
        if path == "/media/denied":
            raise PermissionError("Permission denied")
        if path == "/media/missing":
            raise FileNotFoundError("Folder vanished")
        return self.directories[path]


def names(model, parent=ROOT_INDEX):
    return [model.data(model.index(row, 0, parent)) for row in range(model.rowCount(parent))]


def find(model, name, parent=ROOT_INDEX):
    return next(model.index(row, 0, parent) for row in range(model.rowCount(parent))
                if model.data(model.index(row, 0, parent)) == name)


def test_lazy_remote_navigation_filter_and_worker_thread(qtbot):
    sftp = FakeSftpClient()
    model = SftpDirModel(sftp, "/media")
    tree = QTreeView()
    qtbot.addWidget(tree)
    tree.setModel(model)
    tree.show()
    root = QModelIndex()
    if model.canFetchMore(root):
        model.fetchMore(root)
    qtbot.waitUntil(lambda: "movie.MP4" in names(model))
    assert names(model) == ["clips", "denied", "missing", "movie.MP4"]
    assert sftp.calls == ["/media"]
    assert sftp.threads[0] != QApplication.instance().thread()
    folder = find(model, "clips")
    assert model.data(folder, Qt.ItemDataRole.UserRole) == "/media/clips"
    assert model.data(folder, Qt.ItemDataRole.UserRole + 1) is True
    assert model.hasChildren(folder)
    assert model.canFetchMore(folder)
    assert sftp.calls == ["/media"]
    tree.expand(folder)
    qtbot.waitUntil(lambda: names(model, folder) == ["inside.mkv"])
    assert model.parent(find(model, "inside.mkv", folder)) == folder
    assert not model.canFetchMore(folder)
    assert sftp.calls == ["/media", "/media/clips"]
    model.set_show_all(True)
    assert names(model) == ["clips", "denied", "missing", "movie.MP4", "notes.txt"]
    assert names(model, find(model, "clips")) == ["inside.mkv"]
    assert sftp.calls == ["/media", "/media/clips"]
    model.set_show_all(False)
    assert "notes.txt" not in names(model)
    assert sftp.calls == ["/media", "/media/clips"]


@pytest.mark.parametrize(("folder", "message"), [
    ("denied", "Permission denied"),
    ("missing", "Folder vanished"),
])
def test_inline_error_row_does_not_block_other_folders(qtbot, folder, message):
    model = SftpDirModel(FakeSftpClient(), "/media")
    model.fetchMore(QModelIndex())
    qtbot.waitUntil(lambda: folder in names(model))
    failing = find(model, folder)
    model.fetchMore(failing)
    qtbot.waitUntil(lambda: model.rowCount(failing) == 1)
    error = model.index(0, 0, failing)
    assert model.data(error) == f"Can't list: {message}"
    assert model.data(error, Qt.ItemDataRole.ToolTipRole) == f"Can't list: {message}"
    assert model.flags(error) == Qt.ItemFlag.NoItemFlags
    working = find(model, "clips")
    model.fetchMore(working)
    qtbot.waitUntil(lambda: names(model, working) == ["inside.mkv"])


def test_invalid_remote_entries_are_inline_errors(qtbot):
    sftp = FakeSftpClient()
    sftp.directories["/media"] = [entry("../escape"), entry("clip.mkv"),
                                  SimpleNamespace(filename="unknown", st_mode=None)]
    model = SftpDirModel(sftp, "/media")
    model.fetchMore(QModelIndex())
    qtbot.waitUntil(lambda: model.rowCount() == 3)
    assert "clip.mkv" in names(model)
    assert "Can't list: invalid filename" in names(model)
    assert "Can't list: missing file type" in names(model)
    assert not model.index(-1, 0).isValid()
    assert not model.index(0, 1).isValid()


def test_nonabsolute_remote_root_is_rejected():
    with pytest.raises(ValueError, match="absolute SFTP path"):
        SftpDirModel(FakeSftpClient(), "../media")


@pytest.mark.sftp
def test_container_lists_media_and_missing_folder_inline(qtbot, sftp_server, tmp_path):
    known = KnownHosts(tmp_path / "missing_user", tmp_path / "app" / "known_hosts")
    with paramiko.Transport((sftp_server.host, sftp_server.port)) as transport:
        transport.start_client(timeout=10)
        known.remember(sftp_server.host, sftp_server.port, transport.get_remote_server_key())
        assert known.classify(sftp_server.host, sftp_server.port, transport.get_remote_server_key()) == "trusted"
        transport.auth_password("password", sftp_server.password)
        with paramiko.SFTPClient.from_transport(transport) as sftp:
            model = SftpDirModel(sftp, "/media")
            model.fetchMore(QModelIndex())
            qtbot.waitUntil(lambda: "h264_25.mp4" in names(model), timeout=10000)
            assert model.data(find(model, "h264_25.mp4"), Qt.ItemDataRole.UserRole) == "/media/h264_25.mp4"
            denied = SftpDirModel(sftp, "/root")
            denied.fetchMore(QModelIndex())
            qtbot.waitUntil(lambda: denied.rowCount() == 1, timeout=10000)
            assert "Permission denied" in denied.data(denied.index(0, 0))
            missing = SftpDirModel(sftp, "/media/no-such-folder")
            missing.fetchMore(QModelIndex())
            qtbot.waitUntil(lambda: missing.rowCount() == 1, timeout=10000)
            assert missing.data(missing.index(0, 0)).startswith("Can't list:")
            assert Path(__file__).parent.joinpath("media", "h264_25.mp4").exists()
