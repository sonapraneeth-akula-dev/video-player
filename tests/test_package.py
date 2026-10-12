import runpy
import sys
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import vplayer


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
