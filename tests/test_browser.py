from pathlib import Path
from shutil import copyfile

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from vplayer.settings import Settings
from vplayer.ui.browser import BrowserDock
from vplayer.ui.main_window import MainWindow

MEDIA = Path(__file__).resolve().parent / "media" / "h264_25.mp4"


def test_media_filter_hides_text_until_all_files_enabled(qtbot, tmp_path):
    (tmp_path / "clip.mp4").touch()
    (tmp_path / "notes.txt").touch()
    (tmp_path / "subfolder").mkdir()
    browser = BrowserDock(root=tmp_path)
    qtbot.addWidget(browser)
    browser.show()

    def names():
        index = browser.tree.rootIndex()
        return {browser.model.fileName(browser.model.index(row, 0, index))
                for row in range(browser.model.rowCount(index))}

    qtbot.waitUntil(lambda: "clip.mp4" in names())
    assert "subfolder" in names()
    assert "notes.txt" not in names()
    browser.all_files.setChecked(True)
    qtbot.waitUntil(lambda: "notes.txt" in names())
    browser.all_files.setChecked(False)
    qtbot.waitUntil(lambda: "notes.txt" not in names())


def test_ctrl_b_toggles_browser_dock(qtbot, tmp_path):
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    window.show()
    try:
        assert window.browser.isVisible()
        window.activateWindow()
        qtbot.waitUntil(window.isActiveWindow)
        assert window.browser.toggleViewAction().shortcut().toString() == "Ctrl+B"
        window.browser.tree.setFocus()
        qtbot.waitUntil(window.browser.tree.hasFocus)
        QTest.qWait(200)
        with qtbot.waitSignal(window.browser.toggleViewAction().triggered, timeout=2000):
            QTest.keyClick(window.browser.tree, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        qtbot.waitUntil(lambda: not window.browser.isVisible())
        QTest.keyClick(window.browser.tree, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        qtbot.waitUntil(window.browser.isVisible)
    finally:
        window.close()


def test_browser_double_click_folder_then_enter_file(qtbot, tmp_path):
    folder = tmp_path / "videos"
    folder.mkdir()
    clip = folder / "clip.mp4"
    copyfile(MEDIA, clip)
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    tree = window.browser.tree
    model = window.browser.model
    tree.setRootIndex(model.setRootPath(str(tmp_path)))
    window.show()
    try:
        qtbot.waitUntil(lambda: window.video._render is not None, timeout=10000)
        qtbot.waitUntil(
            lambda: model.index(str(folder)).isValid()
            and not tree.visualRect(model.index(str(folder))).isEmpty()
        )
        folder_index = model.index(str(folder))
        tree.setCurrentIndex(folder_index)
        tree.setFocus()
        QTest.keyClick(tree, Qt.Key.Key_Return)
        qtbot.waitUntil(lambda: tree.rootIndex() == folder_index)
        tree.setRootIndex(model.index(str(tmp_path)))
        qtbot.waitUntil(lambda: not tree.visualRect(folder_index).isEmpty())
        tree.scrollTo(folder_index)
        center = tree.visualRect(folder_index).center()
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseDClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=center)
        qtbot.waitUntil(lambda: tree.rootIndex() == folder_index)

        qtbot.waitUntil(lambda: model.index(str(clip)).isValid())
        clip_index = model.index(str(clip))
        tree.setCurrentIndex(clip_index)
        tree.setFocus()
        activated = []
        window.browser.file_activated.connect(activated.append)
        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            QTest.keyClick(tree, Qt.Key.Key_Return)
        assert window.player._uri == str(clip)
        assert activated == [str(clip)]
        center = tree.visualRect(clip_index).center()
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseDClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=center)
        assert activated == [str(clip), str(clip)]
    finally:
        window.close()


def test_keyboard_only_opens_file_and_reaches_video_focus(qtbot, tmp_path):
    folder = tmp_path / "videos"
    folder.mkdir()
    clip = folder / "clip.mp4"
    copyfile(MEDIA, clip)
    window = MainWindow(Settings(tmp_path / "settings.ini"))
    qtbot.addWidget(window)
    tree = window.browser.tree
    model = window.browser.model
    tree.setRootIndex(model.setRootPath(str(tmp_path)))
    window.show()
    try:
        window.activateWindow()
        qtbot.waitUntil(window.isActiveWindow)
        qtbot.waitUntil(lambda: window.video._render is not None, timeout=10000)
        assert window.browser.accessibleName() == "Local browser"
        assert window.browser.all_files.accessibleName() == "Show all files"
        assert tree.accessibleName() == "Local files"
        assert window.video.accessibleName() == "Video playback"

        window.browser.all_files.setFocus()
        qtbot.waitUntil(lambda: window.browser.all_files.hasFocus() and not window.video_focus.isVisible())
        QTest.keyClick(window.browser.all_files, Qt.Key.Key_Tab)
        assert tree.hasFocus()
        qtbot.waitUntil(lambda: model.index(str(folder)).isValid())
        tree.setCurrentIndex(model.index(str(folder)))
        QTest.keyClick(tree, Qt.Key.Key_Return)
        qtbot.waitUntil(lambda: tree.rootIndex() == model.index(str(folder)))
        qtbot.waitUntil(lambda: model.index(str(clip)).isValid())
        tree.setCurrentIndex(model.index(str(clip)))
        with qtbot.waitSignal(window.player.file_loaded, timeout=10000):
            QTest.keyClick(tree, Qt.Key.Key_Return)
        assert window.player._uri == str(clip)

        QTest.keyClick(tree, Qt.Key.Key_Tab)
        assert window.video.hasFocus()
        assert window.video_focus.widget() is window.video
        assert window.video_focus.isVisible()
        QTest.keyClick(window.video, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
        assert tree.hasFocus()
        assert not window.video_focus.isVisible()
    finally:
        window.close()
