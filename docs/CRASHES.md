# Native crash investigation

Status as of 2026-10-13 (updated after the investigation below). This document separates confirmed findings from
suspected causes; a passing individual test is not evidence that the full
application is crash-free.

## Observed failures

| Signature | Observation | Status |
|---|---|---|
| `0xC0000409` (`FAST_FAIL_FATAL_APP_EXIT`, subcode `0x7`) | A Windows dump traced `QMessageLogger::fatal` through `QOpenGLContext::makeCurrent`, `QOpenGLWidget` destruction, Shiboken deallocation, and Python thread-state cleanup. The video widget was being destroyed outside the intended GUI-thread shutdown sequence. | The identified teardown defect was fixed in `3be44ea` (`0.24.1`); targeted regression tests pass. |
| `0xC0000005` (`-1073741819`) | Intermittent access violation in broader, uninstrumented Windows pytest runs, including runs after the teardown fix. Windows Error Reporting records it as `python312.dll+0x83929`, inside `_PyEval_EvalFrameDefault`. | **Root-caused and fixed 2026-10-12** (render-callback use-after-free, see below). Still: do not count test cases printed before a non-zero process exit as a passing run. |
| `0xe24c4a02` | The pinned Windows libmpv/LuaJIT emits this SEH exception; enabling Python's fault handler exposed it even in runs that continued. | Harmless on its own. **Confirmed 2026-10-12:** with `faulthandler` enabled, printing tracebacks for this exception while the mpv event thread runs ends in `0xC0000005`. Keep `-p no:faulthandler`; use `faulthandler.dump_traceback_later()` (watchdog only) or py-spy instead. |
| Hang, one core at 100% | `test_corrupt_corpus_keeps_process_and_event_loop_alive` timed out (400 s); its worker froze on `corrupt_16_flipped.mkv`. | **Root-caused and fixed 2026-10-12** (libmpv decoder-fallback loop, see below). |

## 2026-10-12 investigation

**Both problems were still present.** On this RDP machine the unmodified
`0.25.0` tree gave, uninstrumented: `pytest -q` exit `-1073741819` after
~36 s; `pytest -v` 11 min with the corrupt-corpus worker timing out; a
second full `-q` run (after a first, incomplete hang fix) exit
`-1073741819` at ~88 %.

### Access violation: freed ctypes callback called by mpv's render thread

The faulting address is inside the Python bytecode interpreter, the signature
of native code jumping into a freed ctypes thunk. The only Python callback
mpv invokes from its own threads in the non-SFTP suite is the render
`update_cb`. Old `MpvWidget.release()` did:

```python
self._render.update_cb = None   # python-mpv: drops old RenderUpdateFn, *then* re-registers
self._render.free()
```

python-mpv's `update_cb` setter assigns the new `RenderUpdateFn` (freeing the
old thunk) **before** calling `mpv_render_context_set_update_callback`. While
video plays, mpv's thread can call the old pointer inside that window →
`0xC0000005` (or `0xC000001D`, illegal instruction). It fires at window or
widget teardown, so the crash surfaces near whatever test runs next (the full
run died just after `test_transport.py`). Confirmed with a stress script
swapping `update_cb` during 60 fps playback: 3/3 runs crashed
(`-1073741819`, `-1073741795`).

**Fix:** `release()` now calls `free()` without touching `update_cb`;
`mpv_render_context_free` guarantees no callback after it returns.
Regression: `test_release_frees_render_context_without_swapping_update_callback`
(fails on the old code).

### Hang: libmpv decoder-fallback loop

A watchdog stack dump showed the GUI thread blocked in `mpv_get_property`
while one native mpv thread burned a core. Reproduced with bare libmpv, no
Qt: `corrupt_16_flipped.mkv` has HEVC extradata no decoder can open. With
`hwdec=auto-safe` mpv tries `d3d11va-copy` (device OK, codec open fails),
then software (also fails), then logs *"Attempting next decoding method
after failure of hevc-…"* and retries software **forever** on the core
thread. Every client API call waits on that thread, so the GUI freezes and
even `mpv_terminate_destroy` cannot return.

| `hwdec` | Result |
|---|---|
| `no` | responsive (one failed open, video track dropped, audio plays) |
| `d3d11va-copy`, `auto-copy`, `auto-safe` | hangs (a hw candidate reaches codec open, then fails) |
| `nvdec-copy`, `vaapi-copy` | responsive (device creation fails first) |

`vd-lavc-software-fallback` and `vd-queue-enable` do not help. Any machine
with a usable hw device hits this on such a file: a bug in the pinned
shinchiro `20261011` libmpv, not Qt/RDP.

**Fix:** each load is a two-step `loadfile`. `Player._loadfile()` first loads
with file-local `hwdec=no`, `ao=null`, `vo=null` and a marker
`force-media-title` (software probe; tracks stay selected so audio-only files
still load). On its `FILE_LOADED` (mpv event thread), the player reloads the
same path with `hwdec=auto-safe` if a video decoder opened (`video-codec`
set), else `hwdec=no`. Undecodable video therefore never reaches the looping
hw path. Null outputs matter: with the real `libmpv` video output the probe
waits on the GUI render thread and added ~0.8 s to first frame.
Rejected: switching `hwdec` at runtime after load reinitialises the decoder
under already-queued frames and broke 10+ frame-exact tests; probing with
`aid=no` broke audio-only files (no track → no `FILE_LOADED`).
Because a hw attempt can still fail mid-stream and fall back (e.g. 4:4:4 test
clips on d3d11va), `file_loaded` is now emitted at the first
`PLAYBACK_RESTART` after the real load, once decoding has settled. Frame
steps issued during that fallback could be lost: `tests/test_frame_accuracy.py`
was already flaky on the original code here (2 runs: 5 and 2 failures) and
is better but not fully stable with the change (2 runs: 0 and 1 failure).
Cost: one extra file open per load (SFTP included).
Regression: `test_undecodable_video_with_hwdec_keeps_core_responsive`
(subprocess; `TimeoutExpired` on the old code).

**Follow-up race (found and fixed the same day).** The reload runs on mpv's
event thread; if the window closed at that moment, `terminate()` cleared the
handle under it (`access violation reading 0x…40`, surfaced by python-mpv as
a `RuntimeWarning`). `_on_event` and `close()` now share `_close_lock`, and
the event thread skips the reload once closed.
Regression: `test_close_during_probe_reload_does_not_touch_freed_handle`
(fails 3/3 without the lock).

**Validation after all fixes:** full uninstrumented suite on this RDP box:
process exit 0, 256 passed, 54 skipped (Docker/SFTP and packaged-build tests),
no warnings. `test_file_menu_opens_frame_and_errors_are_nonblocking` is back
within budget. The frame-step tests can still flake here (see above).

### Other observations

- One run hung at *startup* in `platform.system()` → `_wmi_query` (via
  `keyring` → `jaraco.context`): a Windows WMI stall, not vplayer; a rerun
  answered in 0.35 s. Diagnose with `py-spy dump --pid <pid>`.
- `pytest -q` redirected to a file is block-buffered; an empty log is not a
  hang by itself.
- Without ProcDump/cdb, `Get-WinEvent` (Application, Id 1000) gives the
  faulting module/offset; map it to the nearest export to orient.

The environment used for these observations was a Windows Remote Desktop
session with virtualized graphics. Software OpenGL did not reliably prevent
the crash; audio-only playback without video output survived repeated focused
runs, while some combined OpenGL/default-audio runs crashed on exit. These
fit the render-callback race above (no video render context → no
`update_cb`), but a controlled non-RDP run on comparable hardware has not
been performed.

## What changed

`MpvWidget.dispose()` now rejects calls outside the Qt GUI thread, releases
the mpv render context, and explicitly destroys the Qt widget. On window
close, `MainWindow.closeEvent()` disposes the video surface **before**
`Player.close()` terminates mpv. Standalone rendered-widget tests use the
same ordering. `tests/test_mpv_widget.py` checks repeated playback/teardown,
the destruction thread, and rejection of off-thread disposal. These changes
addressed the *identified* `0xC0000409` lifetime defect. At the time, the
separate intermittent access violation remained; `d8185c2` subsequently
identified and fixed the render-callback use-after-free (described above).
`cc95725` added the probe-reload close lock and reduced its first-frame cost.

The deterministic 50-file corrupt-media test passed four fresh Windows GUI
processes. Before the callback fix, three full runs under ProcDump exited
cleanly, but subsequent uninstrumented broader suites still failed. After
both fixes, an uninstrumented full run exited 0 with 256 passing tests and no
warnings. Later Windows and Ubuntu CI suites progressed through hundreds of
tests without the identified Windows access violation. A later Ubuntu run
(`38378468250`) exited with signal 11 / code 139 during
`test_speed_nudges_are_decimal_and_bounded` after many native tests shared
one Xvfb process. A previous combined run stalled before the corrupt-corpus
worker. The corrupt worker passed when isolated; splitting the remaining
Ubuntu tests into fresh, bounded Xvfb groups subsequently passed CI run
`38380466187` and the documentation run `38381677213`. This contains
runner instability without identifying the newer Ubuntu fault's root cause
or proving long-lived playback crash-free. Non-RDP Windows and
physical-GPU/Wayland crash validation remain open.

Windows run `38382763090` subsequently timed out after 20 minutes: its last
reported result was the end of the codec tests, immediately before the
corrupt-corpus tests. The previous run passed the same boundary. The corpus
passed in a separate process in run `38390000306`, but a ten-file Windows
group then timed out at the start of
`test_unplayable_tab_shows_reason_without_interrupting_other_tab`.

Ubuntu run `38390000306` also segfaulted at
`test_speed_nudges_are_decimal_and_bounded`, the same test as run
`38378468250`, after other native tests in its ten-file group. CI now runs
each remaining test file in a fresh pytest process, and each Ubuntu file
under a fresh Xvfb display, while preserving aggregate coverage. This
isolates accumulated test state, not a demonstrated root cause or production
fix.

Unexpected Python exceptions in UI slots and worker threads are logged and
reported in the active window's error banner; unexpected mpv event/property
callback failures are logged and sent to that window on the Qt thread. This
containment does **not** catch native access violations or libmpv fast-fails.

The first published GitHub Actions run (`38191869176`) failed **before**
Ubuntu tests: Ubuntu's FFmpeg did not recognize `-fps_mode` in
`scripts/make_test_media.py`; the Windows job was canceled. That fixture
compatibility problem has since been fixed; it was not evidence of a native
crash or its absence.

## Reproduction and next evidence

From a Windows checkout with Python 3.12, the pinned Windows libmpv DLL,
and FFmpeg installed, generate test media, then run:

```powershell
.\.venv\Scripts\python.exe scripts\make_test_media.py
.\.venv\Scripts\python.exe -m pytest -q
$LASTEXITCODE
```

Record the **process exit code**, not only pytest's last printed summary.
For remaining release validation, repeat uninstrumented full runs under both
RDP and a non-RDP desktop with the same Python, libmpv DLL, media, and audio
settings. If `0xC0000005` reappears, compare exception codes and stacks and
identify the faulting thread before changing playback code. Keep dumps,
logs containing private paths, SSH material, and process memory **outside
Git**. The fixed defects have focused regressions, but passing CI does not
replace validation on the affected non-RDP and physical-GPU setups.

Further technical history and upstream alternatives are tracked in the
[technical design](plans/2026-10-11_video-player_technical-design.md#13-risks--open-questions).
