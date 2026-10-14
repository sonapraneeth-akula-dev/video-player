# Development setup and build

![VPlayer UI](ui-screenshot.png)

VPlayer can be run from source or built as a portable Windows bundle;
the Windows installer passes hosted install/upgrade/uninstall smoke tests.
The Linux AppImage is built and codec-tested locally on Ubuntu 22.04,
but interactive desktop UAT remains open. Run commands from the
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

CI isolates the native player-lifecycle and corrupt-corpus tests in separate
pytest processes on Windows, and the corrupt corpus on Ubuntu. Other test
files run one at a time in fresh pytest processes on Windows and fresh
pytest/Xvfb displays on Ubuntu. All files append their coverage; the
combined result must still meet the 80% line-coverage gate. Steps have
timeouts so a native stall cannot consume an unbounded runner session.
Isolation does not establish the root cause of shared-process native crashes.

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
In Preferences, Hardware decoding defaults to **Automatic** (`auto-safe`).
Select **Software decoding only** (`no`) if a device has a problematic
hardware decoder; the choice applies to open windows and persists for new
tabs. The log records `hwdec-current` for decoded video. An unavailable
hardware decoder falls back to software without a dialog. GPU-specific
zero-copy performance and Ubuntu X11/Wayland hardware decoding remain
unverified on the owner's devices.

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

The strict local 4K HEVC back-step gate uses a separate ignored, indexed
300-frame/GOP-250 fixture and measures 50 deterministic positions. Generate
it and run the benchmark on each target desktop (on Ubuntu, substitute
`./.venv/bin/python`):

```powershell
.\.venv\Scripts\python.exe scripts\make_test_media.py --backstep
$env:VPLAYER_4K_PERF = "1"
.\.venv\Scripts\python.exe -m pytest -q -s tests\test_backstep_perf.py
```

The gate remains open: on this Windows RDP session, decoder
`hwdec-current=no` gave about 2.0 s p95 against the required 300 ms. An
unavailable GPU decoder and a headless Ubuntu container cannot validate the
desktop performance target; a representative Windows/Ubuntu GPU run is still
required.

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
The manually triggered **Linux and macOS packages** workflow builds and uploads
the portable and installable artifacts on their respective hosted OS runners.

| OS | Prerequisites | Portable | Installable |
|---|---|---|---|
| Windows | `scripts\fetch_libmpv.py`; [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup --scope user`) | `VPlayer-<v>-windows-x64-portable.zip`: unzip, run `vplayer\vplayer.exe` | `VPlayer-<v>-windows-x64-setup.exe`: per-user, no admin; Start menu, optional PATH, "Open with" and "Open in new VPlayer window"; clean uninstall |
| Linux | Ubuntu 22.04 `libmpv1`, `qmake6`, Python 3.12 with `.[package]`, [linuxdeploy](https://github.com/linuxdeploy/linuxdeploy/releases), [Qt plugin](https://github.com/linuxdeploy/linuxdeploy-plugin-qt/releases) and [appimagetool](https://github.com/AppImage/appimagetool/releases) on `PATH` | `VPlayer-<v>-linux-<arch>.AppImage`: `chmod +x`, run | `VPlayer-<v>-linux-<arch>.tar.gz`: extract, `./install.sh` (`--uninstall` to remove only files managed by that installer) |
| macOS | `brew install mpv` (libmpv is bundled into the app) | `VPlayer-<v>-macos-<arch>.zip`: unzipped `VPlayer.app` | `VPlayer-<v>-macos-<arch>.dmg` |

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[package]"
.\.venv\Scripts\python.exe scripts\package.py
$env:VPLAYER_BIN = "$PWD\dist\vplayer\vplayer.exe"; .\.venv\Scripts\python.exe -m pytest tests\test_codecs.py -k packaged
.\scripts\smoke_windows_installer.ps1 -InstallerPath (Get-Item dist\VPlayer-*-windows-x64-setup.exe).FullName
```

On Ubuntu 22.04, install `libmpv1`, `qmake6` and Python 3.12, then obtain executable
`linuxdeploy`, `linuxdeploy-plugin-qt` and `appimagetool` from their linked
releases above, rename them to those three names, and place them on `PATH`.
Keep the Qt plugin discoverable by linuxdeploy. Set `QMAKE` if qmake6 is
installed at a nonstandard path. From the repository root:

```sh
python3.12 -m venv .venv
./.venv/bin/python -m pip install -e '.[package,dev]'
VPLAYER_PYTHON="$PWD/.venv/bin/python" sh packaging/linux/build-appimage.sh
VPLAYER_BIN="$PWD/build/VPlayer.AppDir/AppRun" \
  ./.venv/bin/python -m pytest -q tests/test_codecs.py -k packaged
APPIMAGE_EXTRACT_AND_RUN=1 "$PWD/dist/VPlayer-<version>-linux-<arch>.AppImage" --version
```

Replace the artifact name with the generated version and architecture. The
codec tests use an individual `xvfb-run` session per packaged probe when
`DISPLAY` is unset. They test the uncompressed AppImage payload so a container
without FUSE need not decompress the entire image 25 times. In containers
without FUSE, set `APPIMAGE_EXTRACT_AND_RUN=1` for the AppImage build tools
and the direct archive smoke above. A headless Xvfb codec probe does not
replace interactive X11/Wayland desktop UAT on a clean Ubuntu 22.04 VM.

Set `VPLAYER_LIBMPV` to override which libmpv file the bundle includes.
The installer smoke test changes the current user's PATH temporarily and refuses
to run if VPlayer is already installed. Uninstall and a PATH-off upgrade remove
only the installer-managed entry and preserve existing PATH separators.
The smoke test checks the Open With ProgID and new-window verbs for all 11
video extensions, Start menu shortcut removal, and preservation of a
pre-existing PATH entry.
Packages are unsigned: Windows SmartScreen and macOS Gatekeeper warn on first
launch. Settings and logs stay in the user profile, also for the portable build.
Windows packages passed installer install/uninstall, PATH and registry cleanup,
and the packaged codec matrix. A Linux AppImage was built inside Ubuntu 22.04
using the distro `libmpv1`; the 25-case packaged codec matrix passed under
Xvfb and the artifact was launched in a separate clean Ubuntu 22.04 container.
The Linux installer script passed install/upgrade/uninstall and ownership checks
in an Ubuntu 22.04 container using a dummy AppImage. Interactive Ubuntu
X11/Wayland VM UAT and all macOS packaging remain untested. The Linux installer
refuses to overwrite an unmanaged VPlayer path; remove any earlier unmanaged
installation explicitly before using it.

## Install and uninstall

On Windows, download the `VPlayer-<version>-windows-x64-setup.exe` artifact,
replace `<version>` below with its version number, and run it as your own user:

```powershell
& ".\VPlayer-<version>-windows-x64-setup.exe"
& "$env:LOCALAPPDATA\Programs\VPlayer\vplayer.exe" --version
& "$env:LOCALAPPDATA\Programs\VPlayer\unins000.exe"
```

The last command uninstalls VPlayer at the installer's **default** location.
If you chose another directory, uninstall through **Settings > Apps > Installed
apps** instead. Uninstall removes only the PATH entry the installer added; a
new terminal is needed to see any PATH changes.

On Ubuntu 22.04, install `libxcb-cursor0` before running the AppImage.
`libmpv1` is needed for **source/development** runs; the AppImage carries the
runtime from the machine on which it was built. Extract the matching
`VPlayer-<version>-linux-<arch>.tar.gz` distribution, then run the included
installer from that directory:

```sh
sudo apt-get install -y libxcb-cursor0
tar -xzf VPlayer-<version>-linux-<arch>.tar.gz
cd VPlayer-<version>-linux-<arch>
./install.sh
~/.local/bin/vplayer --version
./install.sh --uninstall
```

Use the archive's actual version and architecture in those commands. The
installer copies the AppImage to `~/.local/bin/vplayer` and registers its
desktop entries and icon; `--uninstall` removes only files it installed. The
Linux AppImage still needs clean Ubuntu 22.04 **desktop** UAT; headless
container validation is not a substitute for release testing on X11 and Wayland.
