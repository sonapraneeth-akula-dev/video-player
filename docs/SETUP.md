# Development setup and build

VPlayer `0.32.0` can be run from source or built as a portable Windows bundle;
the Windows installer passes hosted install/upgrade/uninstall smoke tests,
but full release/UAT and the Linux AppImage are not yet verified. Run commands from the
repository root. The supported development target is Windows 10/11 x64 or
Ubuntu 22.04 with a desktop display; release testing on both operating systems
is still in progress.

## Prerequisites

| Requirement | Windows | Ubuntu 22.04 |
|---|---|---|
| Python | Python **3.12.x** with `venv` and `pip`; the project requires `>=3.12,<3.13` | Install Python **3.12.x** and its `venv`/`pip` support separately; Ubuntu's default Python is not the project's interpreter |
| Video runtime | `scripts\fetch_libmpv.py` downloads and SHA-256-verifies the pinned `libmpv-2.dll` into ignored `vendor\`; requires internet access and `tar` on `PATH` | `sudo apt-get install libmpv1 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxkbcommon-x11-0`; requires a working desktop/OpenGL display |
| Test media | `ffmpeg` and `ffprobe` on `PATH`, with H.264, HEVC, VP9, and AV1 encoders | Same; the generator uses `-fps_mode` when available and legacy `-vsync 0` otherwise |
| SFTP tests | Docker with a running **Linux-container** engine | Docker with a running Linux-container engine; the netem test runs `tc` in the test container via privileged `docker exec` |

Check `python --version`, `ffmpeg -version`, `ffprobe -version`, and, for SFTP
tests, `docker info` before running setup. The first published Ubuntu CI run (`38191869176`) stopped at media generation
because its FFmpeg lacked `-fps_mode`; the generator now uses `-vsync 0` on
older builds. The next run (`38232464757`) stopped at Windows DLL fetch because
the runner's temporary directory and workspace were on different drives;
the fetcher now extracts beside its destination. Ubuntu run `38233993707`
then identified a missing `libxkbcommon-x11.so.0` before the first Qt test.
The XCB dependency preflight subsequently identified missing
`libxcb-icccm.so.4` and `libxcb-keysyms.so.1`; CI now installs all three
packages. Run `38244292254` passed on both OSes: 269 Windows and 292 Ubuntu
tests passed with 83.16% and 85.04% coverage, respectively. The Ubuntu netem
latency test passed twice in that run, though earlier runs narrowly exceeded
its 2-second seek limit; performance is not yet consistently within budget.
Rendered-frame tests need a real display/OpenGL context: Qt's `offscreen`
backend has not passed their frame checks.

## Windows (PowerShell)

`py -3.12` selects Python 3.12 when the Windows Python launcher is installed;
otherwise use a `python` executable whose `--version` reports 3.12.x.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe scripts\fetch_libmpv.py
.\.venv\Scripts\python.exe scripts\make_test_media.py
.\.venv\Scripts\python.exe -m vplayer --version
.\.venv\Scripts\python.exe -m vplayer
```

The fetched DLL is pinned and verified by `scripts\fetch_libmpv.py`; do not
commit its `vendor\` directory. `-e '.[dev]'` installs the application plus
pytest, pytest-qt, coverage, Ruff, and test utilities into this virtual
environment. The media command creates ignored files in `tests\media\`.
Use **File > Open** to load a local recording.

## Ubuntu 22.04 (shell)

Python 3.12 must already be installed; `python3.12 --version` should work.
The following installs the desktop runtime and development dependencies:

```sh
sudo apt-get update
sudo apt-get install -y ffmpeg libmpv1 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxkbcommon-x11-0 xvfb
python3.12 -m venv .venv
./.venv/bin/python -m pip install -e '.[dev]'
./.venv/bin/python scripts/make_test_media.py
./.venv/bin/python -m vplayer --version
./.venv/bin/python -m vplayer
```

Use `xvfb-run -a` around test commands on a headless Linux runner, not around
an interactive desktop launch.

## Tests and checks

Generate fixtures once per checkout (or after deleting `tests\media\`). To
generate the additional deterministic 50-file damaged-media corpus, run
`scripts\make_test_media.py --corrupt` **after** the normal generator; this
step needs its codec fixtures. The commands below show Windows paths; on
Ubuntu use `./.venv/bin/python` and `/` separators instead.

```powershell
.\.venv\Scripts\python.exe scripts\make_test_media.py --corrupt
.\.venv\Scripts\python.exe -m ruff check src scripts tests
.\.venv\Scripts\python.exe -m pytest -q
docker info
.\.venv\Scripts\python.exe -m pytest -q -m sftp
.\.venv\Scripts\python.exe -m pytest -q -s tests\test_sftp_perf.py
```

The SFTP fixture builds and later removes a disposable OpenSSH container.
If Docker is missing, its daemon is unavailable, or it is running Windows
containers, pytest **skips** those tests; check `docker info --format '{{.OSType}}'`
for `linux` when SFTP coverage matters. The performance
test prints first-frame and completed-seek timings under 50 ms / 50 Mbit
network shaping. Pytest disables its fault-handler plugin by project config;
do not mistake a printed test summary followed by a native nonzero process
exit for a pass. See [Native crash investigation](CRASHES.md).

## Build artifact

The setuptools project can build a Python wheel using `pip`. Build isolation
may download the setuptools version required by `pyproject.toml`:

```powershell
.\.venv\Scripts\python.exe -m pip wheel --no-deps --wheel-dir dist .
```

On Ubuntu, replace the Python path with `./.venv/bin/python`. The wheel is a
**Python package**, not a self-contained video player: Windows still needs a
discoverable `libmpv-2.dll`, and Ubuntu needs `libmpv1` and desktop libraries.
The checked-out Windows app finds the fetched DLL in `vendor\`; that directory
is **not** bundled into the wheel. `build\` and `dist\` are ignored by Git.

## Portable and installable packages

`scripts/package.py` builds a self-contained PyInstaller one-folder bundle
(app, Python, Qt and libmpv) and then both package kinds **for the OS it runs
on**. PyInstaller cannot cross-compile, so run it once per OS.
The manually triggered **Windows package** GitHub Actions workflow builds
both Windows artifacts, checks the installer size, runs the packaged
codec/container matrix, smoke-tests fresh installs with PATH on/off, an upgrade
from PATH on to off, and uninstall, and uploads the results. Run `38243446517`
passed all of these checks for version `0.27.0`.

| OS | Prerequisites | Portable | Installable |
|---|---|---|---|
| Windows | `scripts\fetch_libmpv.py`; [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup --scope user`) | `VPlayer-<v>-windows-x64-portable.zip`: unzip, run `vplayer\vplayer.exe` | `VPlayer-<v>-windows-x64-setup.exe`: per-user, no admin; Start menu, optional PATH, "Open with" and "Open in new VPlayer window"; clean uninstall |
| Linux | `libmpv1` (bundled from the build machine; build on Ubuntu 22.04 for widest reach), [appimagetool](https://github.com/AppImage/appimagetool/releases) on `PATH` | `VPlayer-<v>-linux-<arch>.AppImage`: `chmod +x`, run | `VPlayer-<v>-linux-<arch>.tar.gz`: extract, `./install.sh` (`--uninstall` to remove only files managed by that installer) |
| macOS | `brew install mpv` (libmpv is bundled into the app) | `VPlayer-<v>-macos-<arch>.zip`: unzipped `VPlayer.app` | `VPlayer-<v>-macos-<arch>.dmg` |

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[package]"
.\.venv\Scripts\python.exe scripts\package.py
$env:VPLAYER_BIN = "$PWD\dist\vplayer\vplayer.exe"; .\.venv\Scripts\python.exe -m pytest tests\test_codecs.py -k packaged
.\scripts\smoke_windows_installer.ps1 -InstallerPath (Get-Item dist\VPlayer-*-windows-x64-setup.exe).FullName
```

Set `VPLAYER_LIBMPV` to override which libmpv file the bundle includes.
The installer smoke test changes the current user's PATH temporarily and refuses
to run if VPlayer is already installed. Uninstall and a PATH-off upgrade remove
only the installer-managed entry and preserve existing PATH separators.
The smoke test checks the Open With ProgID and new-window verbs for all 11
video extensions, Start menu shortcut removal, and preservation of a
pre-existing PATH entry.
Packages are unsigned: Windows SmartScreen and macOS Gatekeeper warn on first
launch. Settings and logs stay in the user profile, also for the portable build.
Only the Windows packages have been built and tested so far (installer
install/uninstall, PATH and registry cleanup, and the packaged codec matrix).
The Linux installer script passed install/upgrade/uninstall and ownership checks
in an Ubuntu 22.04 container using a dummy AppImage; the actual AppImage and
desktop UAT, and all macOS packaging, remain untested. The Linux installer
refuses to overwrite an unmanaged VPlayer path; remove any earlier unmanaged
installation explicitly before using it.
