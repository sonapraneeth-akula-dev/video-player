import runpy
import sys
import tarfile
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import pytest

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
    binaries = recorded["analysis"]["binaries"]
    assert binaries[0] == (str(libmpv), ".")
    if sys.platform == "linux":
        assert {Path(src).name for src, _ in binaries[1:]} == {
            "libwayland-client.so.0", "libwayland-cursor.so.0", "libwayland-egl.so.1",
        }
    else:
        assert len(binaries) == 1
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
    monkeypatch.setattr(
        package.shutil, "which",
        lambda command: command if command in ("appimagetool", "linuxdeploy", "linuxdeploy-plugin-qt") else None,
    )
    calls = []

    def fake_run(tool, *args, **kwargs):
        calls.append((tool, args))
        if tool == "appimagetool":
            args[-1].write_bytes(b"image")

    monkeypatch.setattr(package, "run", fake_run)
    folder = dist / "vplayer"
    (folder / "_internal").mkdir(parents=True)
    (folder / "vplayer").write_bytes(b"executable")
    (folder / "_internal" / "libQt6Core.so.6").write_bytes(b"qt")
    image, kit = package.linux(vplayer.__version__, folder)
    assert image.read_bytes() == b"image"
    assert (package.BUILD / "VPlayer.AppDir" / "vplayer.png").read_bytes().startswith(b"\x89PNG")
    appdir = package.BUILD / "VPlayer.AppDir"
    assert (appdir / "usr" / "bin" / "vplayer").read_bytes() == b"executable"
    assert b"usr/bin/vplayer" in (appdir / "AppRun").read_bytes()
    assert calls[0] == (
        "linuxdeploy",
        ("--appdir", appdir, "--library", appdir / "usr" / "bin" / "_internal" / "libQt6Core.so.6",
         "--desktop-file", appdir / "vplayer.desktop", "--icon-file", appdir / "vplayer.png",
         "--plugin", "qt"),
    )
    with tarfile.open(kit) as archive:
        names = {Path(name).name for name in archive.getnames()}
    assert {"install.sh", "vplayer.desktop", "vplayer-new-window.desktop", "vplayer.png", image.name} <= names


@pytest.mark.parametrize("missing", ("appimagetool", "linuxdeploy", "linuxdeploy-plugin-qt"))
def test_linux_package_requires_all_deploy_tools(tmp_path, monkeypatch, missing):
    monkeypatch.setattr(package, "BUILD", tmp_path / "build")
    monkeypatch.setattr(package.shutil, "which", lambda tool: None if tool == missing else tool)
    with pytest.raises(SystemExit, match="needs appimagetool, linuxdeploy and linuxdeploy-plugin-qt"):
        package.linux("0.1.0", tmp_path / "vplayer")
    assert not package.BUILD.exists()


def test_linux_desktop_entries_declare_comprehensive_video_mime_types():
    from vplayer.installer import MIME_TYPES

    root = Path(__file__).resolve().parents[1] / "packaging" / "linux"
    expected_mime_line = "MimeType=" + ";".join(MIME_TYPES) + ";"
    for filename in ("vplayer.desktop", "vplayer-new-window.desktop"):
        lines = (root / filename).read_text(encoding="utf-8").splitlines()
        assert "Categories=AudioVideo;Video;Player;" in lines
        assert expected_mime_line in lines

