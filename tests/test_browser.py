from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from vplayer.settings import Settings
from vplayer.ui.browser import BrowserDock
from vplayer.ui.main_window import MainWindow


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
        with qtbot.waitSignal(window.browser.toggleViewAction().triggered, timeout=2000):
            QTest.keyClick(window, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        qtbot.waitUntil(lambda: not window.browser.isVisible())
        QTest.keyClick(window, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        qtbot.waitUntil(window.browser.isVisible)
    finally:
        window.close()
