# Discovery: Desktop Video Player (local + SFTP, frame-accurate)
**Date**: 2026-10-11 | **Status**: Approved (2026-10-11) | **Owner**: soakula

## 1. Idea Summary
A lightweight, VLC-like desktop video player for Windows and Linux that plays local files and
streams directly from remote servers over SFTP without ever writing a local copy. It targets
precise review work: exact playback speeds, frame-by-frame stepping (forward and back), n-frame
skips, and native-resolution snapshots — every action reachable by both a UI control and a
rebindable keyboard shortcut. It must stay stable on very long files and flaky networks, and
install cleanly with OS integration (PATH, desktop entry, "Open with").

## 2. Problem & Motivation
- **What breaks today**: Reviewing media that lives on remote servers means `scp`-ing multi-GB
  files first (slow, eats disk, leaves copies of possibly sensitive data) or mounting via
  sshfs/rclone (extra tooling, caching layers, poor behaviour on drops).
- Mainstream players cover pieces but not the whole workflow: VLC's frame step is forward-only;
  mpv has back-step but no GUI/file browser/SFTP UI; neither offers one place to rebind every
  action with matching toolbar buttons.
- **Cost of doing nothing**: wasted transfer time and disk, stray copies of remote data, and
  context-switching between tools for frame-accurate review.

## 3. Users & Stakeholders
| Role | Needs | Technical level | Permissions |
|------|-------|-----------------|-------------|
| Reviewer / analyst (primary) | Frame-accurate inspection of local + remote video, snapshots | High (comfortable with SSH) | Local user; SSH creds to remote hosts |
| Casual viewer | Open file, play, seek, fullscreen | Low–medium | Local user |
| Installer / admin | One-step install, PATH, file associations | Medium | Per-user by default; admin optional |
| Maintainer (owner) | Small, stable codebase; reproducible builds | High | Repo owner |

## 4. Goals & Success Criteria
- **Goal**: Stream remote video with zero local copies — **Measured by**: 0 bytes of media written
  to disk during a 2 h SFTP session (file-system monitoring of temp/cache dirs).
- **Goal**: Frame-accurate navigation — **Measured by**: +1/−1 frame step lands on the exact
  adjacent frame (PTS check) in 100% of CFR test clips across H.264/HEVC/VP9/AV1.
- **Goal**: Low memory — **Measured by**: steady-state RSS < 250 MB playing 4K HEVC; growth
  < 5% over 8 h continuous playback.
- **Goal**: Never crash — **Measured by**: 0 crashes across corrupt-file corpus and scripted
  network-drop tests (NFR-004/005).
- **Goal**: Full keyboard + UI parity — **Measured by**: every action in the action registry has
  both a visible control and a rebindable shortcut (automated check).

## 5. Scope
### In Scope
- Local playback with integrated file browser.
- SFTP browsing + streaming (password, key, or agent auth).
- Speeds: presets 0.25, 0.5, 0.67, 1.0, 2.0, 4.0 + fine custom increments.
- Frame step ±1, skip ±n frames (configurable n), time seeks.
- Hardware-accelerated decode with automatic software fallback.
- Snapshot to PNG/JPEG at native resolution (quick-save to default dir + "Save As" dialog).
- Volume/mute, fullscreen, seek bar, audio/subtitle track selection.
- Customizable shortcuts with conflict detection, persisted settings.
- Multiple tabs per window and multiple windows, each tab playing its own video.
- Packaging: Windows installer (PATH, "Open with"), Linux install (`.desktop`, icon, MIME).

### Out of Scope (Non-Goals)
- Custom decoder/demuxer — _Rationale: mature engines (libmpv/libvlc/FFmpeg) already do this; reimplementing is years of work and a stability risk._
- macOS — _Rationale: not requested; engine choice should keep it possible later._
- Other remote protocols (SMB, FTP, WebDAV, HTTP/DLNA) — _Rationale: SFTP is the stated need; add on demand._
- Editing/trimming/transcoding — _Rationale: player, not editor._
- Playlists/library management, metadata scraping — _Rationale: not part of review workflow; v2 candidate._
- DRM content / streaming services — _Rationale: licensing; outside product purpose._
- Plaintext storage of SSH passwords — _Rationale: security; OS keyring or agent only._

## 6. Key Scenarios / User Journeys
### Open a local file from the OS
User right-clicks `clip.mp4` in Explorer / Nautilus → "Open with <App>" → player opens and starts
playing within ~1 s. Typing `<app> clip.mp4` in a terminal does the same (PATH).

### Stream a remote file over SFTP
User opens "Connect to server", enters host, port, username, chooses key/agent or password, and
confirms the host-key fingerprint on first connect. They browse remote folders, pick a 40 GB
recording, and playback starts quickly. Seeking far ahead fetches only the needed byte ranges.
Nothing is written to local disk.

### Frame-accurate review
User pauses, presses next-frame repeatedly, steps back two frames, then skips 10 frames forward.
Current frame number and timestamp are always visible. They take a snapshot; a PNG at native
resolution is saved to the default folder with a name containing source name and timestamp, and
a toast confirms the path.

### Network drop mid-stream
Wi-Fi drops while streaming. Playback pauses with a "reconnecting…" indicator; the player retries
with backoff, reconnects, and resumes at the same position. If retries are exhausted the user sees
a clear error and the app remains usable.

### Work with several videos at once
User has a local recording open and opens two remote files from the same server; each opens in
its own tab in the same window. Switching tabs shows each video at its own position and speed.
They open a new window for a different server and keep both windows side by side. Opening another
file from Explorer/Nautilus while the app is running adds it to the app rather than replacing a
video that's already playing. Choosing "Open in new window" instead opens it in a fresh window.

### Synced compare
User opens two recordings of the same event (one local, one remote) in synced-compare view, side
by side in one window. The second recording started 2.4 s later, so they set a 2.4 s offset. Now
play, pause, speed changes and frame steps move both videos together. They toggle sync off to
nudge one side by a frame, toggle it back on, then snapshot both sides as two PNGs.

### Rebind shortcuts
User opens Preferences → Shortcuts and rebinds "Step back 1 frame" to `,`. The UI warns that `,`
is already bound and offers to swap. The binding persists across restarts and the toolbar
tooltip reflects the new key.

## 7. Functional Requirements
| ID | Requirement | Priority | Notes |
|----|-------------|----------|-------|
| FR-001 | The system shall provide an integrated local file browser filtered to supported media extensions, with an "all files" toggle. | Must | |
| FR-002 | The system shall open a file passed as a command-line argument (local path or `sftp://` URI). | Must | Needed for "Open with" + PATH |
| FR-003 | The system shall connect to an SFTP server using password, private key (with passphrase), or SSH agent authentication. | Must | |
| FR-004 | The system shall verify server host keys against `known_hosts` and require explicit user confirmation for unknown or changed keys. | Must | No silent accept |
| FR-005 | The system shall browse remote SFTP directories and play a selected file by streaming byte ranges on demand. | Must | |
| FR-006 | The system shall not write any media bytes to local disk during playback (no temp files, no disk cache). | Must | RAM read-ahead only |
| FR-007 | The system shall bound in-memory network buffers per stream: read-ahead (default 64 MB) and back-buffer for seeking/back-step (max 256 MB). | Must | Owner confirmed 256 MB max 2026-10-11 |
| FR-008 | The system shall support playback speed presets 0.25x, 0.5x, 0.67x, 1.0x, 2.0x, 4.0x. | Must | |
| FR-009 | The system shall support custom speed increments/decrements with a configurable step (default 0.05x) within 0.05x–8.0x. | Must | |
| FR-010 | The system shall preserve audio pitch at non-1.0 speeds, with an option to disable. | Should | |
| FR-011 | The system shall step forward exactly one frame, pausing first if playing. | Must | |
| FR-012 | The system shall step backward exactly one frame. | Must | Engine must support back-step |
| FR-013 | The system shall skip forward and backward by n frames, n user-configurable (default 10). | Must | |
| FR-014 | The system shall display current frame number, timestamp, and total duration. | Must | Frame number labelled approximate for VFR |
| FR-015 | The system shall seek by configurable time intervals (default 5 s / 60 s) and via a seek bar. | Must | |
| FR-016 | The system shall use hardware-accelerated decoding when available and fall back to software automatically on failure. | Must | |
| FR-017 | The system shall decode at least H.264, HEVC, VP9, AV1 video and AAC, MP3, Opus, AC-3 audio in MP4, MKV, WebM, MOV, AVI, TS containers. | Must | |
| FR-018 | The system shall capture the current video frame at native resolution (no overlays, no scaling) and save as PNG or JPEG. | Must | |
| FR-019 | The system shall support snapshot quick-save to a configurable default directory and a "Save As" dialog. | Must | Default format PNG |
| FR-020 | The system shall name quick-saved snapshots `<source>_<HH-MM-SS.mmm>_f<frame>.<ext>` and never overwrite existing files. | Should | |
| FR-021 | The system shall provide volume control, mute, and fullscreen toggle. | Must | |
| FR-022 | The system shall expose every user action (play/pause, speed, frame step, skip, seek, snapshot, volume, mute, fullscreen, open, connect) as both a UI control and a keyboard shortcut. | Must | Single action registry |
| FR-023 | The system shall let users rebind any shortcut, detect conflicts, reset to defaults, and persist bindings. | Must | |
| FR-024 | The system shall show each action's current shortcut in its tooltip/menu entry. | Should | |
| FR-025 | The system shall recover from SFTP disconnects by pausing, retrying with backoff, and resuming at the last position. | Must | |
| FR-026 | The system shall continue playback past corrupt/undecodable packets and show a non-blocking error if a file is unplayable. | Must | |
| FR-027 | The system shall allow selecting audio and subtitle tracks, including external subtitle files. | Should | |
| FR-028 | The system shall remember recent files and saved SFTP connection profiles, with secrets only in the OS keyring. | Should | |
| FR-029 | The Windows installer shall install the app, add it to PATH (default on, deselectable), and register "Open with" for common media types. | Must | Per-user install default |
| FR-030 | The Linux install shall provide a `.desktop` entry, icon, and MIME associations so the app appears in "Open With". | Must | |
| FR-031 | Uninstall shall remove PATH entries, associations, shortcuts, and desktop entries. | Must | |
| FR-032 | The system shall resume local files from the last position. | Could | |
| FR-033 | The system shall support A-B loop for repeated segment review. | Could | |
| FR-034 | The system shall support remote protocols other than SFTP. | Won't | v1 |
| FR-035 | The system shall open multiple videos as tabs within a window, each with independent playback state (position, speed, volume, tracks). | Must | Owner confirmed 2026-10-11 |
| FR-036 | The system shall support multiple top-level windows, each with its own set of tabs. | Must | Owner confirmed 2026-10-11 |
| FR-037 | Keyboard shortcuts and toolbar actions shall apply to the active tab of the focused window only. | Must | |
| FR-038 | The system shall provide actions to open a new tab, close a tab, switch to the next/previous tab, and open a new window, each with UI control + shortcut. | Must | Extends FR-022 |
| FR-039 | Background tabs shall auto-pause when not visible by default, with a user setting to keep playing (muted or with audio). | Should | Owner confirmed default 2026-10-11 |
| FR-040 | The system shall allow at most 4 tabs per window and show a clear message when the limit is reached. | Must | Owner confirmed 2026-10-11; memory guard |
| FR-041 | The system shall let a tab be dragged out into a new window or between windows without losing playback state. | Must | Owner confirmed 2026-10-11 |
| FR-042 | Opening a file via "Open with"/CLI while the app runs shall add it as a new tab in the last-used window; if that window already has 4 tabs, it opens in a new window. | Must | Owner confirmed 2026-10-11 |
| FR-043 | The system shall offer an explicit "Open in new window" option in the OS "Open with" context menu, in the in-app file browsers, and as a CLI flag. | Must | Owner confirmed 2026-10-11 |
| FR-044 | The system shall show two videos side by side in one window in a synced-compare view. | Must | Owner confirmed 2026-10-11 |
| FR-045 | In synced-compare view, play/pause, seek, speed changes, frame step (±1) and n-frame skips shall apply to both videos together. | Must | |
| FR-046 | In synced-compare view, the user shall be able to set a time or frame offset between the two videos and toggle sync off to adjust one side alone. | Must | Aligns recordings that started at different times |
| FR-047 | In synced-compare view, snapshot shall offer capturing the active side or both sides (as separate PNGs at native resolution). | Should | |
| FR-048 | The system shall refuse to open two videos in synced-compare view if their frame rates differ, showing an error with both frame rates; each video can still be played in its own tab. | Must | Owner confirmed 2026-10-11. Compare nominal fps as exact fractions (30000/1001 ≠ 30) |
| FR-049 | In synced-compare view, the system shall show buffer health for each side when streaming over SFTP. | Should | |

## 8. Non-Functional Requirements
| ID | Category | Target | Notes |
|----|----------|--------|-------|
| NFR-001 | Memory | Local: RSS < 250 MB playing one 4K HEVC video; each additional paused tab adds < 60 MB. SFTP: same, plus per-stream buffers capped at 64 MB read-ahead + 256 MB back-buffer | Worst case 4 tabs × 2 windows bounded by FR-040 |
| NFR-002 | Memory stability | RSS growth < 5% over 8 h; 24 h soak with no crash | |
| NFR-003 | Disk | 0 bytes of media written to disk during SFTP playback | Procmon / `inotifywait` |
| NFR-004 | Robustness | 0 crashes over a corpus of ≥ 50 corrupt/truncated/fuzzed files | |
| NFR-005 | Robustness | 0 crashes over 100 scripted network drops (1–60 s) during SFTP streaming | |
| NFR-006 | Startup | Cold start to first frame < 1.5 s for local file on SSD | |
| NFR-007 | SFTP latency | First frame < 3 s and seek < 2 s on 50 ms RTT / 50 Mbps link | |
| NFR-008 | Frame accuracy | ±1 step correct in 100% of CFR clips; local back-step p95 < 300 ms for GOP ≤ 250. Remote back-step served from the ≤ 256 MB back-buffer; slower when it must re-fetch from the server (accepted) | Synced compare: both sides land on the target frame |
| NFR-009 | Input latency | UI action → visible response p95 < 100 ms | |
| NFR-010 | Security | Host-key verification enforced; secrets only in OS keyring (Credential Manager / Secret Service) | |
| NFR-011 | Accessibility | Full keyboard operability, visible focus, accessible names on controls; WCAG 2.2 AA where applicable | |
| NFR-012 | Portability | Windows 10 22H2+ / 11 x64; Ubuntu 22.04 x64 (X11 and Wayland — under Wayland, run via XWayland if native video embedding misbehaves) | Owner's Linux: Ubuntu 22.04 |
| NFR-013 | Install footprint | Installer < 120 MB; per-user install without admin rights | |
| NFR-014 | Licensing | GPL/LGPL components (incl. GPL libmpv builds) acceptable; personal use only, no redistribution | Re-review if ever shared (§12) |

## 9. Constraints & Assumptions
Owner decisions are marked "owner confirmed"; remaining assumptions to validate during design/build.
- **Constraint**: Windows 10/11 + Ubuntu 22.04, x64 only for v1.
- **Constraint**: Windows installer unsigned (personal use); Linux ships as AppImage + install script (owner confirmed 2026-10-11).
- **Constraint**: No local caching/copying of remote media — bounded in-memory buffering only.
- **Constraint**: Reuse a mature media engine; no custom codecs.
- **Constraint**: Personal use only; not shared or distributed (owner confirmed 2026-10-11) → GPL components and bundled HEVC/AAC decoders acceptable.
- **Constraint**: Python is the primary language; Rust only where a feature can't meet its requirements in Python (owner confirmed 2026-10-11).
- **Assumption**: Typical media is up to 4K, 1–10 h, H.264/HEVC, streamed over VPN (owner accepted default 2026-10-11) — _Validated by: buffer/latency tests on a VPN link._
- **Assumption**: Remote servers run standard OpenSSH SFTP — _Validated by: tests against OpenSSH 8.x/9.x._
- **Assumption**: Most review content is CFR; VFR frame numbers may be shown as approximate — _Validated by: sample of real files._
- **Assumption**: Back-step (re-decode from keyframe) < 300 ms is acceptable on long-GOP 4K — _Validated by: benchmark, 4K HEVC, 250-frame GOP._
- **Assumption**: Per-user install (no admin) is the preferred Windows default — _Validated by: owner confirmation._
- **Assumption**: Python meets NFR-001/006/007 since the native engine does the heavy lifting — _Validated by: memory/latency spike; a miss triggers a targeted Rust module, not a rewrite._

## 10. Prior Art & Research
- [mpv](https://mpv.io/) / [libmpv client API](https://github.com/mpv-player/mpv/blob/master/include/mpv/client.h) — embeddable engine with `frame-step`, `frame-back-step`, exact `speed`, `screenshot-to-file` (native res, `video` mode), `hwdec=auto-safe`, and a stream-callback API (`mpv_stream_cb_add_ro`) to feed bytes from memory. **Best fit**: covers FR-008–FR-019 natively; back-step is first-class.
- [VLC / libvlc](https://www.videolan.org/vlc/libvlc.html) — native `sftp://` access (libssh2) and snapshots, but frame step is forward-only; back-step needs seek hacks. Weaker fit for FR-012.
- [python-mpv](https://github.com/jaseg/python-mpv) — Python libmpv binding incl. `register_stream_protocol` → in-memory SFTP stream, no temp file. Pairs with PySide6.
- [Paramiko](https://www.paramiko.org/) / [AsyncSSH](https://asyncssh.readthedocs.io/) — SFTP with random-access reads, prefetch, agent/key auth, `known_hosts`.
- [FFmpeg `sftp` protocol (libssh)](https://ffmpeg.org/ffmpeg-protocols.html#sftp) — mpv can open `sftp://` directly if FFmpeg was built with libssh; build-dependent, poor host-key UX → prefer app-side stream callback.
- [SMPlayer](https://www.smplayer.info/), [Celluloid](https://celluloid-player.github.io/), [MPC-HC](https://github.com/clsid2/mpc-hc), [mpv.net](https://github.com/mpvnet-player/mpv.net) — prove the "GUI shell + mpv" pattern; none has an integrated SFTP browser.
- [sshfs-win](https://github.com/winfsp/sshfs-win) / [rclone mount](https://rclone.org/commands/rclone_mount/) — mount remote so any player works. Viable "buy" option but adds dependencies and caching layers (rclone VFS cache conflicts with FR-006).
- [Freedesktop Desktop Entry spec](https://specifications.freedesktop.org/desktop-entry-spec/latest/) and [shared-mime-info](https://specifications.freedesktop.org/shared-mime-info-spec/latest/) — govern FR-030.
- [Windows OpenWithProgids](https://learn.microsoft.com/en-us/windows/win32/shell/fa-progids) — governs FR-029 "Open with" without hijacking defaults.
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/) — reference for NFR-011.
- [RFC 4251 §4.1 host keys](https://www.rfc-editor.org/rfc/rfc4251#section-4.1) — governs FR-004.

**Build-vs-buy finding**: `mpv` + config + `sshfs` already covers ~80% for a power user. Real
gaps justifying a build: integrated SFTP browser with **no disk caching**, GUI parity for every
action, a shortcut-rebinding UI, and OS integration. Keep the app a thin shell over libmpv —
don't drift into rebuilding the engine.

## 11. Suggestions & Opportunities
- **Single action registry** driving toolbar, menus, tooltips, and shortcuts → FR-022/023/024 for free; parity checkable by one test.
- **On-screen frame/timecode overlay** (toggle) — snapshots must exclude it (FR-018).
- **Copy timestamp/frame number to clipboard** — cheap, high value for reporting.
- **Reuse `~/.ssh/config`** host aliases and agent → zero-friction connect.
- **Buffer-health indicator** for SFTP streams; tune read-ahead for high-RTT links.
- **Local rotating log** (no media bytes, no secrets) for diagnosing field issues.
- **Edge cases**: VFR and open-GOP back-step; files > 4 GB / > 24 h; seek past EOF; rotation metadata (snapshot orientation); HDR → PNG tone-mapping; HiDPI; remote file modified/truncated mid-play; SSH idle timeouts (keepalive); permission-denied dirs; non-UTF-8 filenames; many tabs open at once (memory pressure, multiple GPU decoders — hardware decoders have session limits, so fall back to software per tab); several tabs streaming from the same SFTP server (reuse one SSH connection, one channel per file); closing a window with tabs still streaming.
- **Abuse/security**: host-key spoofing (FR-004); passphrases held in memory only as long as needed; malicious crafted media (keep FFmpeg current); installer modifies PATH only with its own directory.
- **Sequencing / cut from v1**: A-B loop, resume position, external subtitles. Ship order: (1) local playback + action registry + frame/speed/snapshot, (2) tabs + multiple windows + synced compare, (3) SFTP streaming + reconnect, (4) packaging/OS integration, (5) Should/Could items.

## 12. Risks & Open Questions
- [x] **Licensing**: libmpv is LGPL only if built with `-Dgpl=false`; most prebuilt Windows libmpv builds are GPL. PySide6 is LGPL; PyQt6 is GPL/commercial. — _Resolved 2026-10-11: GPL acceptable; app is for personal use only, not shared. Re-review if that ever changes._
- [x] **Codec patents**: HEVC/AAC via bundled FFmpeg. — _Resolved 2026-10-11: not a concern for personal, non-distributed use. Re-review before any distribution._
- [x] **Shell stack**: — _Resolved 2026-10-11: Python (PySide6 + python-mpv + Paramiko). Rust only where a feature can't meet its requirements in Python, added as a targeted extension module (e.g. PyO3/maturin), not a rewrite. See "Shell Stack Options" below._
- [x] **Remote back-step**: — _Resolved 2026-10-11: in-RAM back-buffer capped at 256 MB per stream; slower remote back-step beyond that is accepted (FR-007, NFR-008)._
- [x] **Windows code signing**: — _Resolved 2026-10-11: unsigned; personal use only._
- [x] **Linux packaging format**: — _Resolved 2026-10-11: AppImage + install script writing `.desktop`, icon, MIME._
- [x] **Single vs multi-instance**: — _Resolved 2026-10-11: multiple tabs per window AND multiple windows (FR-035/036)._
- [x] **Background tabs**: — _Resolved 2026-10-11: auto-pause by default (FR-039)._
- [x] **Open with while running**: — _Resolved 2026-10-11: new tab in last-used window, plus explicit "Open in new window" option (FR-042/043)._
- [x] **Tab limit**: — _Resolved 2026-10-11: max 4 tabs per window (FR-040)._
- [x] **Tab drag**: — _Resolved 2026-10-11: yes (FR-041)._
- [x] **Synced compare**: — _Resolved 2026-10-11: in v1 (FR-044–047)._
- [x] **Default snapshot format**: — _Resolved 2026-10-11: PNG._
- [x] **Linux setup**: — _Resolved 2026-10-11: Ubuntu 22.04 (NFR-012)._
- [x] **Typical media**: — _Resolved 2026-10-11: default accepted — up to 4K, 1–10 h, H.264/HEVC, over VPN._
- [x] **Synced compare across different frame rates**: — _Resolved 2026-10-11: not allowed; show an error and refuse to open in compare view (FR-048)._
- [x] **Synced compare with SFTP**: — _Resolved 2026-10-11: two remote 4K streams at once (double bandwidth, up to ~640 MB buffers) is acceptable on owner's VPN (FR-049)._

### Shell Stack Options: Python vs Rust
Both options use libmpv (C) for decoding, rendering and buffering. The difference is everything
around it: the window and controls, the file browser, shortcuts, SFTP and packaging. Figures are
estimates, not measurements.

#### Option A: Python + PySide6 + python-mpv + Paramiko
**Pros**
- **Fastest to build.** Estimated 3–5 weeks to cover the Must requirements.
- **Qt supplies most of the UI.** `QFileSystemModel` is the local file browser (FR-001). `QAction`
  gives one list of actions driving toolbar buttons, menus, tooltips and shortcuts
  (FR-022/FR-024). `QKeySequenceEdit` handles shortcut rebinding (FR-023). `QFileDialog` is the
  snapshot "Save As" dialog (FR-019).
- **Embedding video is easy.** mpv draws into a native window handle on Windows and Linux (X11).
- **Well-established libraries.** python-mpv supports feeding SFTP data straight from memory
  (`register_stream_protocol`, FR-006). Paramiko handles keys, the SSH agent and `known_hosts`
  checks (FR-003/FR-004).
- **Easy to change.** Quick to tweak behaviour; many people can contribute.
- **Simple licensing.** PySide6 is LGPL.

**Cons**
- **Higher baseline memory.** ~80–120 MB before any video plays. Still meets NFR-001 (< 250 MB
  for 4K), with less margin.
- **Python's global lock can cause stutter.** Each SFTP read libmpv requests runs Python code
  that needs the interpreter lock; a busy UI or slow network call can stall playback.
  Workaround: background thread/process filling an in-memory read-ahead buffer.
- **Large installer.** PyInstaller + Qt + libmpv ≈ 100–150 MB (NFR-013 target < 120 MB at risk).
  Antivirus tools often flag PyInstaller executables.
- **Errors surface at runtime.** Mistakes in rarely used paths (e.g. reconnect after a drop,
  FR-025) appear as runtime exceptions; the compiler won't catch them.
- **Python runtime packaging.** Bundled, but Python upgrades and Qt plugin packaging on Linux
  can be awkward.
- **Wayland embedding is unreliable.** Native-window embedding misbehaves on Wayland (NFR-012);
  fix means switching to mpv's OpenGL rendering via `QOpenGLWidget`.

#### Option B: Rust + egui (or Slint) + libmpv2 + russh-sftp / ssh2
**Pros**
- **Lowest memory.** ~20–40 MB baseline; no garbage collector or interpreter.
- **Stability enforced by the compiler.** Rules out whole classes of memory and threading bugs;
  errors must be handled explicitly. Best fit for NFR-002/004/005.
- **No global lock.** SFTP stream, decoder and UI run truly in parallel → smoother remote
  playback (NFR-007).
- **Small single executable.** ~20–40 MB including libmpv; far fewer antivirus false positives.
- **Predictable over long sessions.** No garbage-collection pauses during 8–24 h playback.
- **Packaging tools exist.** `cargo-wix` (Windows), `cargo-deb` / `cargo-appimage` (Linux).

**Cons**
- **Slower to build.** Estimated 2–3× longer, ~8–12 weeks for the Must requirements.
- **More UI built by hand.** egui/Slint have no ready-made file browser or shortcut-rebinding
  editor; expect a few hundred lines each.
- **Video embedding takes more work.** mpv's OpenGL rendering inside the egui/Slint window —
  proven, but more code and care around threads and the graphics context.
- **Tauri ruled out.** Its web-based window can't easily host native mpv video.
- **Less mature SFTP libraries.** russh-sftp is pure Rust but younger; ssh2 wraps libssh2
  (mature) but is blocking and needs a C dependency.
- **egui doesn't look native.** Own widget style; Slint looks closer to native.
- **Harder for others to contribute.** Fewer people know Rust; longer compile times.
- **Smaller binding community.** libmpv2 may need direct calls to libmpv's C functions to fill
  API gaps.

#### How to Decide
| If you care most about… | Pick |
|---|---|
| A working version within a month | Python |
| Rich native UI with little effort | Python |
| Lowest memory, smallest installer | Rust |
| Never crashing over long or remote sessions | Rust |
| Smooth SFTP streaming on slow networks | Rust (Python can get close with a background buffer thread) |
| Others contributing or maintaining it | Python |

**Middle path**: build the Python version first to prove the workflow and measure memory against
the targets, then rewrite in Rust only if a target is missed. Both sit on the same libmpv, so the
risk is low.

**Decision (2026-10-11, owner)**: **Python** — PySide6 + python-mpv + Paramiko. Rust is used only
if a specific feature cannot meet its requirements in Python, and then only for that piece, as a
Python extension module (PyO3/maturin). Likeliest candidate: the SFTP read-ahead buffer, if Python's
global lock causes playback stutter (NFR-007). Rewriting the whole app in Rust is not planned.

## 13. Glossary
| Term | Meaning |
|------|---------|
| SFTP | SSH File Transfer Protocol — file access over an SSH connection |
| Zero-copy (here) | No media bytes persisted to local disk; data flows network → bounded RAM buffer → demuxer/decoder |
| Frame step / back-step | Advance / rewind exactly one decoded video frame |
| GOP | Group of Pictures — frames between keyframes; back-step decodes from the previous keyframe |
| CFR / VFR | Constant / variable frame rate |
| hwdec | Hardware decoding (D3D11VA/DXVA2 on Windows; VAAPI/VDPAU/NVDEC on Linux) |
| Action registry | Single table of app actions, each mapped to UI controls and shortcuts |
| Synced compare | Two videos shown side by side whose playback controls move together, with an optional offset |
| RSS | Resident set size — physical memory used by the process |
| libmpv / libvlc | Embeddable playback engines of mpv / VLC |
