# VPlayer

Desktop video player for Windows 10/11 and Ubuntu 22.04 (in development).

## Development

Use Python 3.12 and FFmpeg for test media. From the repository root:

```sh
python -m venv .venv
python -m pip install -e ".[dev]"
```

On Windows, run `python scripts/fetch_libmpv.py` to download the pinned,
SHA-256-verified `libmpv-2.dll` into `vendor/`. The script needs Windows'
built-in `tar`.

On Ubuntu 22.04, run `sudo apt install libmpv1 libxcb-cursor0` instead.

Run `vplayer` or `python -m vplayer`, then use **File > Open** to play a local video.
Use **Space** or the toolbar to play/pause; click or drag the seek bar, or use
**Left/Right** (5 seconds) and **Shift+Left/Right** (60 seconds) to seek.
Use **Up/Down** for volume, **M** for mute, and **F** for fullscreen (**Esc**
to exit).
You can also run `vplayer FILE [FILE ...]` to open paths from the command line,
`vplayer --version` to print the version, or `vplayer --new-window FILE`. Until
tabs and single-instance routing are added, each CLI file opens in its own
window; every launch already creates a new window.
Use **Ctrl+B** to show or hide the local file browser; **All files** reveals
files outside the media extension filter. Double-click or press **Enter** on a
folder to open it, or on a video to play it.
The browser, video surface, and seek bar are reachable with **Tab** and
**Shift+Tab**; the focused video has a visible outline.

Generate the frame-indexed and codec/container media fixtures with
`python scripts/make_test_media.py` (requires FFmpeg and ffprobe), then
run `python -m pytest -q`. Pytest's fault handler is disabled in this project:
the pinned Windows libmpv emits LuaJIT exceptions that can crash the test
process when the handler is installed.
