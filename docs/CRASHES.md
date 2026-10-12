# Native crash investigation

Status as of 2026-10-12. This document separates confirmed findings from
suspected causes; a passing individual test is not evidence that the full
application is crash-free.

## Observed failures

| Signature | Observation | Status |
|---|---|---|
| `0xC0000409` (`FAST_FAIL_FATAL_APP_EXIT`, subcode `0x7`) | A Windows dump traced `QMessageLogger::fatal` through `QOpenGLContext::makeCurrent`, `QOpenGLWidget` destruction, Shiboken deallocation, and Python thread-state cleanup. The video widget was being destroyed outside the intended GUI-thread shutdown sequence. | The identified teardown defect was fixed in `3be44ea` (`0.24.1`); targeted regression tests pass. |
| `0xC0000005` (`-1073741819`) | Intermittent access violation in broader, uninstrumented Windows pytest runs, including runs after the teardown fix. An earlier dump implicated Qt Windows application teardown, but did not establish the precise failing operation or a sole root cause. | **Open.** Do not count test cases printed before this process exit as a passing run. |
| `0xe24c4a02` | The pinned Windows libmpv/LuaJIT emits this SEH exception; enabling Python's fault handler exposed it even in runs that continued. | An observed exception, **not** a confirmed explanation for either crash signature. Pytest disables its fault-handler plugin in `pyproject.toml`. |

The environment used for these observations was a Windows Remote Desktop
session with virtualized graphics. Software OpenGL did not reliably prevent
the crash; audio-only playback without video output survived repeated focused
runs, while some combined OpenGL/default-audio runs crashed on exit. Neither
Remote Desktop, the virtual GPU, audio, nor libmpv has been established as the
sole cause of `0xC0000005`. A controlled non-RDP run on comparable hardware
has not been performed.

## What changed

`MpvWidget.dispose()` now rejects calls outside the Qt GUI thread, releases
the mpv render context, and explicitly destroys the Qt widget. On window
close, `MainWindow.closeEvent()` disposes the video surface **before**
`Player.close()` terminates mpv. Standalone rendered-widget tests use the
same ordering. `tests/test_mpv_widget.py` checks repeated playback/teardown,
the destruction thread, and rejection of off-thread disposal. These changes
address the *identified* `0xC0000409` lifetime defect; they do not resolve or
explain the separate intermittent access violation.

The deterministic 50-file corrupt-media test passed four fresh Windows GUI
processes. Three full runs under ProcDump also exited cleanly, but
instrumentation affects timing, and subsequent uninstrumented broader suites
still failed. Targeted codec and SFTP passes likewise do not establish
full-suite stability. No physical-GPU Windows or Ubuntu crash validation has
been completed.

The first published GitHub Actions run (`38191869176`) failed **before**
Ubuntu tests: Ubuntu's FFmpeg did not recognize `-fps_mode` in
`scripts/make_test_media.py`; the Windows job was canceled. This is a
separate fixture-generation/CI problem, not evidence of a native crash or
its absence.

## Reproduction and next evidence

From a Windows checkout with Python 3.12, the pinned Windows libmpv DLL,
and FFmpeg installed, generate test media, then run:

```powershell
.\.venv\Scripts\python.exe scripts\make_test_media.py
.\.venv\Scripts\python.exe -m pytest -q
$LASTEXITCODE
```

Record the **process exit code**, not only pytest's last printed summary.
Repeat uninstrumented full runs under both RDP and a non-RDP desktop with the
same Python, libmpv DLL, media, and audio settings. Compare native exception
codes and stacks; capture a new dump if `0xC0000005` reproduces, and identify
the faulting thread and operation before changing playback code. Keep dumps,
logs containing private paths, SSH material, and process memory **outside
Git**. A fix needs a focused regression and repeated clean full-process
exits on the affected setup, followed by Windows and Ubuntu validation.

Further technical history and upstream alternatives are tracked in the
[technical design](plans/2026-10-11_video-player_technical-design.md#13-risks--open-questions).
