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

a = Analysis(
    [str(root / "src" / "vplayer" / "__main__.py")],
    pathex=[str(root / "src")],
    binaries=[(libmpv, ".")],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="vplayer", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="vplayer")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="VPlayer.app", bundle_identifier="local.vplayer")
