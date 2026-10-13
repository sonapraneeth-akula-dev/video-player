import runpy
import sys
import tarfile
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import vplayer
from scripts import package


def test_package_version_matches_metadata():
    assert vplayer.__version__ == version("vplayer")
    assert vplayer.APP_NAME == "VPlayer"


def test_spec_bundles_libmpv_without_unused_qt_modules(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    libmpv = tmp_path / "libmpv-2.dll"
    libmpv.touch()
    monkeypatch.setenv("VPLAYER_LIBMPV", str(libmpv))
    recorded = {}

    def analysis(scripts, **options):
        recorded["scripts"] = scripts
        recorded["analysis"] = options
        return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

    def exe(*args, **options):
        recorded["exe"] = options

    runpy.run_path(
        str(root / "packaging" / "vplayer.spec"),
        init_globals={
            "SPECPATH": str(root / "packaging"),
            "Analysis": analysis, "PYZ": lambda *_: None,
            "EXE": exe, "COLLECT": lambda *_args, **_kwargs: None,
            "BUNDLE": lambda *_args, **_kwargs: None,
        },
    )
    assert recorded["scripts"] == [str(root / "src" / "vplayer" / "__main__.py")]
    assert recorded["analysis"]["binaries"] == [(str(libmpv), ".")]
    assert {"PySide6.QtWebEngineCore", "PySide6.Qt3DCore", "PySide6.QtQuick"} <= set(
        recorded["analysis"]["excludes"]
    )
    assert recorded["exe"]["console"] is False
    if sys.platform == "win32":
        assert Path(recorded["exe"]["icon"]).read_bytes().startswith(b"\x00\x00\x01\x00")


def test_linux_package_contains_desktop_templates_and_256_icon(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    monkeypatch.setattr(package, "DIST", dist)
    monkeypatch.setattr(package, "BUILD", tmp_path / "build")
    monkeypatch.setattr(package.shutil, "which", lambda command: "appimagetool" if command == "appimagetool" else None)
    monkeypatch.setattr(package, "run", lambda _tool, _appdir, image, **_kwargs: image.write_bytes(b"image"))
    folder = dist / "vplayer"
    folder.mkdir()
    (folder / "vplayer").write_bytes(b"executable")
    image, kit = package.linux(vplayer.__version__, folder)
    assert image.read_bytes() == b"image"
    assert (package.BUILD / "VPlayer.AppDir" / "vplayer.png").read_bytes().startswith(b"\x89PNG")
    with tarfile.open(kit) as archive:
        names = {Path(name).name for name in archive.getnames()}
    assert {"install.sh", "vplayer.desktop", "vplayer-new-window.desktop", "vplayer.png", image.name} <= names
