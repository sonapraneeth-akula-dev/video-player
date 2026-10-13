# PyInstaller one-folder bundle of VPlayer and libmpv; built by scripts/package.py.
import os
import sys
from glob import glob
from pathlib import Path

root = Path(SPECPATH).parent
if sys.platform == "win32":
    candidates = [str(root / "vendor" / "libmpv-2.dll")]
elif sys.platform == "darwin":
    candidates = ["/opt/homebrew/lib/libmpv.2.dylib", "/usr/local/lib/libmpv.2.dylib"]
else:
    candidates = sorted(glob("/usr/lib/*/libmpv.so.[12]") + glob("/usr/lib/libmpv.so.[12]"))
libmpv = os.environ.get("VPLAYER_LIBMPV") or next((p for p in candidates if Path(p).is_file()), None)
if not libmpv:
    raise SystemExit("libmpv not found; run scripts/fetch_libmpv.py (Windows), install libmpv, or set VPLAYER_LIBMPV")

binaries = [(libmpv, ".")]
if sys.platform == "linux":
    for name in ("libwayland-client.so.0", "libwayland-cursor.so.0", "libwayland-egl.so.1"):
        path = next(iter(glob(f"/usr/lib/*/{name}")), None)
        if path is None:
            raise SystemExit(f"libmpv dependency {name} not found; install Ubuntu's libmpv1 runtime")
        binaries.append((path, "."))

a = Analysis(
    [str(root / "src" / "vplayer" / "__main__.py")],
    pathex=[str(root / "src")],
    binaries=binaries,
    excludes=[
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore", "PySide6.QtQuick",
    ],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="vplayer", console=False,
    icon=str(root / "packaging" / "windows" / "vplayer.ico") if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="vplayer")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="VPlayer.app", bundle_identifier="local.vplayer")
