# Development setup and build

VPlayer `0.25.0` is a source-installed desktop application, not yet a
distributable Windows installer or Linux AppImage. Run commands from the
repository root. The supported development target is Windows 10/11 x64 or
Ubuntu 22.04 with a desktop display; release testing on both operating systems
is still in progress.

## Prerequisites

| Requirement | Windows | Ubuntu 22.04 |
|---|---|---|
| Python | Python **3.12.x** with `venv` and `pip`; the project requires `>=3.12,<3.13` | Install Python **3.12.x** and its `venv`/`pip` support separately; Ubuntu's default Python is not the project's interpreter |
| Video runtime | `scripts\fetch_libmpv.py` downloads and SHA-256-verifies the pinned `libmpv-2.dll` into ignored `vendor\`; requires internet access and `tar` on `PATH` | `sudo apt-get install libmpv1 libxcb-cursor0`; requires a working desktop/OpenGL display |
| Test media | `ffmpeg` and `ffprobe` on `PATH`; the test generator needs FFmpeg's `-fps_mode` option and H.264, HEVC, VP9, and AV1 encoders | Same; the stock Ubuntu 22.04 FFmpeg in the first CI run **did not recognize `-fps_mode`** |
| SFTP tests | Docker with a running **Linux-container** engine | Docker with a running Linux-container engine; the netem test runs `tc` in the test container via privileged `docker exec` |

Check `python --version`, `ffmpeg -version`, `ffprobe -version`, and, for SFTP
tests, `docker info` before running setup. An FFmpeg build lacking `-fps_mode`
cannot generate the current fixtures. The first published Ubuntu CI run
(`38191869176`) stopped at media generation for this reason; use an FFmpeg
build with that option or fix the generator's compatibility before expecting
the Ubuntu test job to pass. This is a known CI blocker, not a test pass.
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
The distro-provided FFmpeg may be too old for the fixture generator, as noted
above. The following installs the desktop runtime and development dependencies:

```sh
sudo apt-get update
sudo apt-get install -y ffmpeg libmpv1 libxcb-cursor0 xvfb
python3.12 -m venv .venv
./.venv/bin/python -m pip install -e '.[dev]'
./.venv/bin/python scripts/make_test_media.py
./.venv/bin/python -m vplayer --version
./.venv/bin/python -m vplayer
```

Run the fixture-generation command only after confirming the installed FFmpeg
supports `-fps_mode`; otherwise it exits with an explicit FFmpeg error. Use
`xvfb-run -a` around test commands on a headless Linux runner, not around an
interactive desktop launch.

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
If Docker is missing or its daemon is unavailable, pytest **skips** those
tests; check `docker info` first when SFTP coverage matters. The performance
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
PyInstaller/Inno Setup packaging, an AppImage, and installer scripts remain
planned tasks in the [Azure task list](plans/2026-10-11_video-player_azure-task-list.md);
there is currently no release-installer build command to run.
