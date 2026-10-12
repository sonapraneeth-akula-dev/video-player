"""Build portable and installable VPlayer packages for the current OS into dist/.

Windows: VPlayer-<v>-windows-x64-portable.zip and VPlayer-<v>-windows-x64-setup.exe (Inno Setup 6)
Linux:   VPlayer-<v>-linux-<arch>.AppImage (portable) and VPlayer-<v>-linux-<arch>.tar.gz
         (AppImage + install.sh; needs appimagetool on PATH)
macOS:   VPlayer-<v>-macos-<arch>.zip (portable .app) and VPlayer-<v>-macos-<arch>.dmg

Requires `pip install -e .[package]` and the platform libmpv (scripts/fetch_libmpv.py on Windows,
libmpv1 on Ubuntu, `brew install mpv` on macOS). PyInstaller cannot cross-build: run on each OS.
"""

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"
PACKAGING = ROOT / "packaging"


def run(*args: object, **kwargs) -> None:
    print("+", " ".join(str(arg) for arg in args), flush=True)
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def bundle() -> Path:
    run(
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", DIST, "--workpath", BUILD / "pyinstaller", PACKAGING / "vplayer.spec",
    )
    folder = DIST / "vplayer"
    run(folder / ("vplayer.exe" if sys.platform == "win32" else "vplayer"), "--version")
    return folder


def windows(version: str, folder: Path) -> list[Path]:
    base = f"VPlayer-{version}-windows-x64"
    portable = Path(shutil.make_archive(str(DIST / f"{base}-portable"), "zip", DIST, folder.name))
    iscc = shutil.which("iscc") or next((
        path for path in (
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        ) if path.is_file()
    ), None)
    if iscc is None:
        raise SystemExit(f"Built {portable}; installer needs Inno Setup 6 (winget install JRSoftware.InnoSetup)")
    run(
        iscc, "/Q", f"/DAppVersion={version}", f"/DSourceDir={folder}", f"/DOutputBase={base}-setup",
        PACKAGING / "windows" / "installer.iss",
    )
    return [portable, DIST / f"{base}-setup.exe"]


def linux(version: str, folder: Path) -> list[Path]:
    tool = shutil.which("appimagetool")
    if tool is None:
        raise SystemExit("appimagetool not found on PATH: https://github.com/AppImage/appimagetool/releases")
    arch = platform.machine()
    appdir = BUILD / "VPlayer.AppDir"
    shutil.rmtree(appdir, ignore_errors=True)
    shutil.copytree(folder, appdir)
    for name in ("vplayer.desktop", "vplayer.svg"):
        shutil.copy2(PACKAGING / "linux" / name, appdir / name)
    apprun = appdir / "AppRun"
    apprun.write_text('#!/bin/sh\nexec "$(dirname "$(readlink -f "$0")")/vplayer" "$@"\n', encoding="utf-8")
    apprun.chmod(0o755)
    image = DIST / f"VPlayer-{version}-linux-{arch}.AppImage"
    run(tool, appdir, image, env={**os.environ, "ARCH": arch})
    kit = DIST / f"VPlayer-{version}-linux-{arch}.tar.gz"
    with tarfile.open(kit, "w:gz") as archive:
        archive.add(image, f"{kit.name[:-7]}/{image.name}")
        for name in ("install.sh", "vplayer.desktop", "vplayer.svg"):
            archive.add(PACKAGING / "linux" / name, f"{kit.name[:-7]}/{name}")
    return [image, kit]


def macos(version: str, _folder: Path) -> list[Path]:
    app = DIST / "VPlayer.app"
    base = DIST / f"VPlayer-{version}-macos-{platform.machine()}"
    run("ditto", "-c", "-k", "--keepParent", app, f"{base}.zip")
    run("hdiutil", "create", "-volname", "VPlayer", "-srcfolder", app, "-ov", "-format", "UDZO", f"{base}.dmg")
    return [Path(f"{base}.zip"), Path(f"{base}.dmg")]


def main() -> None:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    build = {"win32": windows, "darwin": macos}.get(sys.platform, linux)
    for artifact in build(version, bundle()):
        print(f"{artifact}  ({artifact.stat().st_size / 1_048_576:.1f} MiB)")


if __name__ == "__main__":
    main()
