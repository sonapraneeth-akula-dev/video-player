# PRD: VPlayer — Desktop Video Player (local + SFTP, frame-accurate)

## 1. Overview
- **Version**: 1.0  |  **Date**: 2026-10-11  |  **Status**: Approved
- **Sources**: [Discovery (Approved)](../plans/2026-10-11_video-player_discovery.md) ·
  [Technical design (Final)](../plans/2026-10-11_video-player_technical-design.md)
- App name: **VPlayer** / `vplayer` (owner-approved 2026-10-11; may be renamed later).

### Problem Statement
Reviewing video that lives on remote servers today means copying multi-GB files locally first
(slow, eats disk, leaves stray copies of possibly sensitive data) or mounting with sshfs/rclone
(extra tooling, caching layers, poor behaviour on network drops). Existing players cover only part
of the review workflow: VLC can't step backwards, mpv has no GUI, file browser or SFTP UI, and
neither lets every action be rebound with a matching toolbar control.

### Target Users
The owner, as a single user. A technical reviewer/analyst who inspects local and remote recordings
frame by frame on Windows 10/11 and Ubuntu 22.04, often over a VPN. Personal use only; not
distributed (discovery §9).

## 2. Goals & Non-Goals
### Business Goals / User Goals
- Stream remote video with **zero local copies**: 0 bytes of media written to disk during a 2 h
  SFTP session (NFR-003).
- **Frame-accurate navigation**: ±1 frame step lands on the exact adjacent frame in 100% of CFR
  test clips (H.264/HEVC/VP9/AV1) (NFR-008).
- **Low memory**: RSS < 250 MiB playing one 4K HEVC video; < 5% growth over 8 h (NFR-001/002).
- **Never crash**: 0 crashes across ≥ 50 corrupt files and 100 scripted network drops
  (NFR-004/005).
- **Full keyboard + UI parity**: every action has a visible control and a rebindable shortcut
  (FR-022/023), checked automatically.
- **Clean OS integration**: per-user install, PATH, "Open with" on Windows and Ubuntu
  (FR-029–031).

### Non-Goals (Out of Scope)
- Custom decoder/demuxer — _Rationale: libmpv already does this; reimplementing is years of work
  and a stability risk._
- macOS — _Rationale: not requested; the stack keeps it possible later._
- Remote protocols other than SFTP (SMB, FTP, WebDAV, HTTP/DLNA) (FR-034) — _Rationale: SFTP is
  the stated need._
- Editing, trimming, transcoding — _Rationale: player, not editor._
- Playlists, library management, metadata scraping — _Rationale: not part of the review workflow;
  v2 candidate._
- DRM content / streaming services — _Rationale: licensing; outside product purpose._
- Plaintext storage of SSH passwords — _Rationale: security; OS keyring or SSH agent only._
- Code signing, redistribution, store publishing — _Rationale: personal use only (NFR-014);
  unsigned installer accepted._
- Frame-exact ±n skip on VFR files or files with wrong fps metadata — _Rationale: discovery §9
  assumption; VFR is detected best-effort and shown as approximate._

## 3. User Personas
- **Reviewer / analyst (primary — the owner)**: frame-accurate inspection of local and remote
  video, snapshots, side-by-side comparison. High technical level, comfortable with SSH.
- **Casual viewer (same person, lighter use)**: open a file, play, seek, fullscreen. Expects
  VLC-like defaults.
- **Installer / maintainer (same person)**: one-step per-user install and clean uninstall; a
  small, stable Python codebase with reproducible builds.

| Role | Permissions | Key Actions |
|------|-------------|-------------|
| Reviewer | Local user; SSH credentials to remote hosts | Connect, browse, stream, step, skip, compare, snapshot |
| Casual viewer | Local user | Open, play/pause, seek, volume, fullscreen |
| Installer / maintainer | Local user, no admin rights needed | Install, uninstall, rebind shortcuts, change settings |

## 4. Requirements (MoSCoW)
Every discovery FR/NFR is traced to exactly one requirement below (§5 lists the IDs per
milestone).

| ID | Requirement | Priority | Problem it solves | Milestones | Est. AI |
|----|-------------|----------|-------------------|------------|---------|
| REQ-001 | Users shall play local media files reliably with hardware decoding | Must | Can't watch or inspect local recordings | M-001.1, M-001.2, M-001.3 | 06:30 |
| REQ-002 | Users shall stream remote files over SFTP with no local copy and survive network drops | Must | Remote review needs slow copies that leave stray data | M-002.1, M-002.2, M-002.3 | 07:00 |
| REQ-003 | Users shall control playback speed exactly and navigate frame by frame | Must | Review work needs exact speeds and exact frames | M-003.1, M-003.2 | 04:30 |
| REQ-004 | Users shall capture the current frame at native resolution | Must | Findings must be saved as evidence without scaling or overlays | M-004.1 | 01:20 |
| REQ-005 | Every action shall have both a UI control and a rebindable keyboard shortcut | Must | Mixed mouse/keyboard workflows and personal key habits | M-005.1, M-005.2 | 02:55 |
| REQ-006 | Users shall work with several videos in tabs and windows | Must | One video at a time forces constant reopening | M-006.1, M-006.2, M-006.3 | 05:20 |
| REQ-007 | Users shall compare two videos side by side in sync | Must | Aligning two recordings of one event by hand is slow and error-prone | M-007.1, M-007.2 | 04:15 |
| REQ-008 | The app shall install and integrate with Windows and Ubuntu | Must | Manual setup; no "Open with" or PATH | M-008.1, M-008.2 | 03:25 |
| REQ-009 | The app shall stay within memory limits and never crash in long sessions | Must | Long files and many tabs exhaust memory or crash players | M-009.1, M-009.2 | 02:15 |
| REQ-010 | Review conveniences: traceable snapshot names, copy position, tracks/subtitles, pitch, shortcut hints | Should | Small frictions slow down every review | M-010.1, M-010.2, M-010.3 | 03:15 |
| REQ-011 | Users shall reconnect to known servers without retyping details | Should | Re-entering host, user and key each time | M-011.1 | 01:40 |
| REQ-012 | Hidden tabs shall pause by default, with a setting to keep playing | Should | Hidden tabs play audio and burn CPU unexpectedly | M-012.1 | 00:55 |
| REQ-013 | Compare view shall snapshot both sides and show each side's buffer health | Should | Evidence from both sides and streaming status are hard to get in compare | M-013.1 | 01:15 |
| REQ-014 | Local files shall resume from the last position | Could | Long files restart from zero | M-014.1 | 00:50 |
| REQ-015 | Users shall loop an A-B segment | Could | Repeated review of a short segment needs manual seeking | M-015.1 | 00:55 |
| **Total (v1: Must + Should)** | | | | | **44:35** |
| **Total (incl. Could)** | | | | | **46:20** |

Must = 37:30 · Should = 07:05 · Could = 01:45. Could requirements are not in v1 (technical design
§1); they are built only after v1 ships, if wanted.

### Won't Have
- Remote protocols other than SFTP (FR-034) — _Rationale: owner decision; add on demand later._
- Everything in §2 Non-Goals.

## 5. Requirement Breakdown
> Requirement → Milestone → Feature → User Story. Estimates: feature = its stories + 00:10
> verification; milestone = its features + 00:15 exit-criteria run. Test names refer to the
> technical design §10 test table. All memory figures are MiB.

### REQ-001: Local playback (Must Have)
- **Outcome**: Any common local media file opens fast, plays with hardware decoding when
  available, and never takes the app down.
- **Traces**: FR-001, FR-002 (local), FR-015, FR-016, FR-017, FR-021, FR-026, NFR-004, NFR-006,
  NFR-012
- **Est. AI**: 06:30

#### Milestone M-001.1: Play a local file end to end
- **Problem solved**: There is no way to open and watch a local video in the app.
- **Traces**: FR-002 (local path), FR-015, FR-016, FR-021, NFR-006, NFR-012
- **Est. AI**: 03:15

##### FEAT-001.1.1: Video surface and decoding
A PySide6 main window with an `MpvWidget` that draws libmpv output through the OpenGL render API
(AD-002), with `hwdec=auto-safe` and automatic software fallback.
- **Est. AI**: 01:20

- **US-001** — **As a** viewer **I want** to open a local file from File → Open **So that** it
  plays in the window (`Est. AI: 00:40`)
  - [ ] Picking a file starts playback; first frame shows in < 1.5 s on SSD (NFR-006)
  - [ ] Video scales to the window, keeping aspect ratio; works on Windows and on Ubuntu 22.04
    under both X11 and Wayland (NFR-012)
  - [ ] A missing or unreadable path shows a non-blocking error banner, and the app stays usable
- **US-002** — **As a** viewer **I want** hardware decoding with automatic fallback **So that**
  playback is efficient and never fails because of the GPU (`Est. AI: 00:30`)
  - [ ] Hardware decoding is used when available (`hwdec-current` is not `no` on a supported GPU)
  - [ ] If hardware decoding fails or is unavailable, playback continues in software with no
    user action and no error dialog

##### FEAT-001.1.2: Basic transport controls
Play/pause, seek bar, time seeks, volume, mute and fullscreen.
- **Est. AI**: 01:10

- **US-003** — **As a** viewer **I want** play/pause, a seek bar and time seeks **So that** I can
  move through the video (`Est. AI: 00:35`)
  - [ ] Seek bar dragging and clicking seek to the keyframe nearest the target
  - [ ] Short and long time seeks default to ±5 s / ±60 s and are configurable (FR-015)
  - [ ] Seeking before 0 lands at the start; seeking past the end lands on the last frame
- **US-004** — **As a** viewer **I want** volume, mute and fullscreen **So that** I can watch
  comfortably (`Est. AI: 00:25`)
  - [ ] Volume up/down with an on-screen level; mute toggles without changing the volume level
  - [ ] Fullscreen toggles on/off; Esc leaves fullscreen

##### FEAT-001.1.3: Command-line open
- **Est. AI**: 00:30

- **US-005** — **As a** terminal user **I want** `vplayer <path>` to open a file **So that** I can
  start from a shell (`Est. AI: 00:20`)
  - [ ] `vplayer clip.mp4` opens and plays the file; relative paths resolve against the current
    directory
  - [ ] `vplayer --version` prints the version and exits
  - [ ] A non-existent path shows the error banner (not a crash or stack trace)

**Exit Criteria** — milestone is done only when all boxes are checked:
- [ ] **Unit tests**: URI/path parsing and settings for seek intervals pass; ≥ 80% line coverage
  on new code
- [ ] **Integration tests**: pytest-qt + libmpv: open → first frame, play/pause, seek, volume,
  mute, fullscreen (FEAT-001.1.1/2, US-001…US-004)
- [ ] **Performance**: cold start to first frame < 1.5 s on SSD (NFR-006), measured on Windows 11
  and Ubuntu 22.04
- [ ] **Manual / UAT**: owner runs US-001…US-005 on Windows and Ubuntu (X11 + Wayland); hwdec
  fallback confirmed by forcing `hwdec=no`-equivalent failure (US-002)

#### Milestone M-001.2: Browse local media
- **Problem solved**: Finding files needs a separate file manager.
- **Traces**: FR-001
- **Est. AI**: 01:20

##### FEAT-001.2.1: Local file browser dock
A dockable browser (`QFileSystemModel`) filtered to supported media extensions.
- **Est. AI**: 01:05

- **US-006** — **As a** reviewer **I want** to browse local folders filtered to media **So that**
  I find videos quickly (`Est. AI: 00:35`)
  - [ ] Only supported media extensions are shown by default; an "All files" toggle shows
    everything
  - [ ] Filtered-out files are hidden, not greyed out
- **US-007** — **As a** reviewer **I want** to open a file from the browser by double-click or
  Enter **So that** I stay in the app (`Est. AI: 00:20`)
  - [ ] Double-click / Enter on a file plays it in the active tab; on a folder it opens the folder
  - [ ] The browser is fully keyboard-navigable

**Exit Criteria**:
- [ ] **Unit tests**: extension filter and "All files" toggle pass
- [ ] **Integration tests**: pytest-qt browse → open plays the file (US-006, US-007)
- [ ] **Accessibility**: browser reachable and operable by keyboard only, with visible focus
  (NFR-011)

#### Milestone M-001.3: Survive any file
- **Problem solved**: Unusual codecs or damaged files stop playback or crash the player.
- **Traces**: FR-017, FR-026, NFR-004
- **Est. AI**: 01:55

##### FEAT-001.3.1: Codec and container coverage
- **Est. AI**: 00:40

- **US-008** — **As a** reviewer **I want** all common codecs and containers to play **So that**
  I don't need another player (`Est. AI: 00:30`)
  - [ ] H.264, HEVC, VP9, AV1 video and AAC, MP3, Opus, AC-3 audio play in MP4, MKV, WebM, MOV,
    AVI, TS (every combination the container can hold)
  - [ ] Works in the packaged Windows build and the AppImage, not just in development

##### FEAT-001.3.2: Corrupt-file resilience
- **Est. AI**: 01:00

- **US-009** — **As a** reviewer **I want** playback to continue past corrupt packets **So that**
  one damaged section doesn't end my review (`Est. AI: 00:30`)
  - [ ] Damaged packets are skipped; playback continues after them
  - [ ] No crash over the ≥ 50-file corrupt/truncated/fuzzed corpus (NFR-004)
- **US-010** — **As a** reviewer **I want** a clear message for an unplayable file **So that** I
  know what happened and can keep working (`Est. AI: 00:20`)
  - [ ] An unplayable file shows a non-blocking banner with the reason; other tabs keep playing
  - [ ] Unexpected exceptions are logged and shown as an error, never terminating the app

**Exit Criteria**:
- [ ] **Integration tests**: codec/container matrix test passes on the Windows bundle and the
  AppImage (US-008)
- [ ] **Robustness**: corrupt-file corpus (≥ 50 files) → 0 crashes (US-009, NFR-004)
- [ ] **Integration tests**: unplayable file → banner shown, other tabs unaffected (US-010)

### REQ-002: SFTP streaming with zero local copies (Must Have)
- **Outcome**: Remote recordings are browsed and played directly from an SSH server, nothing is
  written to local disk, memory stays bounded, and network drops are recovered.
- **Traces**: FR-002 (sftp URI), FR-003, FR-004, FR-005, FR-006, FR-007, FR-025, NFR-003,
  NFR-005, NFR-007, NFR-010
- **Est. AI**: 07:00

#### Milestone M-002.1: Connect securely
- **Problem solved**: There is no safe way to authenticate to a remote server from the app.
- **Traces**: FR-003, FR-004, NFR-010
- **Est. AI**: 02:30

##### FEAT-002.1.1: Connect dialog and authentication
Paramiko-based connection with password, private key (with passphrase) or SSH agent.
- **Est. AI**: 01:10

- **US-011** — **As a** reviewer **I want** to connect with a password **So that** I can reach
  servers without keys (`Est. AI: 00:30`)
  - [ ] Host, port (default 22), user and password fields; wrong password shows a clear error and
    lets me retry
  - [ ] The password is never written to disk in plaintext; if saved, it goes only to the OS
    keyring (Credential Manager / Secret Service) (NFR-010)
- **US-012** — **As a** reviewer **I want** to connect with a private key or my SSH agent **So
  that** I use my normal SSH setup (`Est. AI: 00:30`)
  - [ ] Private key file with optional passphrase prompt; SSH agent auth when available
  - [ ] An encrypted key with a wrong passphrase shows an error, not a crash

##### FEAT-002.1.2: Host-key verification
- **Est. AI**: 01:05

- **US-013** — **As a** reviewer **I want** to confirm unknown host keys **So that** I'm not
  connected to an impostor (`Est. AI: 00:30`)
  - [ ] An unknown host shows its key fingerprint (SHA-256) and requires explicit accept; reject
    closes the connection
  - [ ] Keys are checked against `~/.ssh/known_hosts` and the app's own known-hosts file; only the
    app file is ever written
- **US-014** — **As a** reviewer **I want** a hard warning on a changed host key **So that** a
  possible attack is never silently accepted (`Est. AI: 00:25`)
  - [ ] A host with trusted entries but no matching key shows a changed-key warning; nothing is
    accepted silently
  - [ ] A changed key during an automatic reconnect is a hard failure (no prompt mid-stream)

**Exit Criteria**:
- [ ] **Unit tests**: host-key trust table passes (old key in `known_hosts` + accepted new key in
  app file → trusted; trusted entries but no match → warning) (US-013, US-014)
- [ ] **Integration tests**: password, key+passphrase and agent auth against the local OpenSSH
  container (US-011, US-012)
- [ ] **Security**: no plaintext secrets in settings or logs (grep of config dir and logs after a
  session); no high/critical findings in dependency scan (NFR-010)

#### Milestone M-002.2: Stream remote files without local copies
- **Problem solved**: Remote files must be copied locally before they can be watched.
- **Traces**: FR-002 (sftp URI), FR-005, FR-006, FR-007, NFR-003, NFR-007
- **Est. AI**: 02:50

##### FEAT-002.2.1: Remote browser
- **Est. AI**: 00:40

- **US-015** — **As a** reviewer **I want** to browse remote folders **So that** I can find the
  recording to play (`Est. AI: 00:30`)
  - [ ] Lists directories and media files on the server, with the same media filter and "All
    files" toggle as the local browser
  - [ ] Permission-denied and missing folders show an inline error; the browser stays usable

##### FEAT-002.2.2: In-memory SFTP stream
A custom mpv stream (`vpsftp://`) reading byte ranges on demand into mpv's RAM-only demuxer cache
(AD-003…AD-006).
- **Est. AI**: 01:55

- **US-016** — **As a** reviewer **I want** to play a remote file directly **So that** I don't
  wait for a download (`Est. AI: 00:45`)
  - [ ] First frame < 3 s and seek < 2 s (first frame at the new position) on a 50 ms RTT /
    50 Mbps link (NFR-007)
  - [ ] Seeking far ahead in a 40 GB file fetches only the needed byte ranges
  - [ ] Frame step, back-step and ±n skip work on remote files as on local ones
- **US-017** — **As a** reviewer **I want** zero disk writes and bounded memory while streaming
  **So that** no copies of remote data are left behind and memory stays predictable
  (`Est. AI: 00:40`)
  - [ ] 0 bytes of media written to disk during a 2 h SFTP session (Procmon on Windows,
    `inotifywait` on Ubuntu) (FR-006, NFR-003)
  - [ ] Per stream: read-ahead ≤ `readahead_mb` (default 64 MiB, including SFTP in-flight
    blocks) and back-buffer ≤ `backbuffer_mb` (max 256 MiB) (FR-007)
- **US-018** — **As a** terminal user **I want** `vplayer sftp://user@host/path` to stream a file
  **So that** I can open remote files from a shell (`Est. AI: 00:20`)
  - [ ] Valid URIs connect (prompting for credentials/host key as needed) and play
  - [ ] Malformed URIs show an error naming the problem

**Exit Criteria**:
- [ ] **Integration tests**: SFTP play/seek/back-step via local OpenSSH container, including the
  peak-buffer assertions (US-016, US-017)
- [ ] **Integration tests**: zero-disk-write check during SFTP playback on both OSes (US-017,
  NFR-003)
- [ ] **Performance**: first frame < 3 s, seek < 2 s with 50 ms RTT / 50 Mbps emulated (NFR-007)
- [ ] **Unit tests**: `sftp://` URI parsing (US-018); `SftpStream` block cache, seek, EOF

#### Milestone M-002.3: Recover from network drops
- **Problem solved**: A short network drop ends the remote playback session.
- **Traces**: FR-025, NFR-005
- **Est. AI**: 01:40

##### FEAT-002.3.1: Transparent reconnect
Reconnect and reseek inside the stream read with backoff 1, 2, 4, 8, 16 s then 30 s
(`retry_max`, default 6) (AD-007).
- **Est. AI**: 01:25

- **US-019** — **As a** reviewer **I want** playback to pause, reconnect and resume by itself
  **So that** a Wi-Fi blip doesn't interrupt my review (`Est. AI: 00:45`)
  - [ ] During a drop, a "Reconnecting… (attempt i)" indicator shows; playback pauses when the
    buffer runs dry
  - [ ] Any outage ≤ 60 s recovers automatically and resumes at the same position, with no
    reload
  - [ ] Closing a tab mid-outage returns within 1 s
- **US-020** — **As a** reviewer **I want** a clear error and Retry when reconnecting fails **So
  that** I can continue once the network is back (`Est. AI: 00:30`)
  - [ ] When retries are exhausted: "Connection lost at <time>" banner with Retry; Retry resumes at
    that position
  - [ ] A normal end of file never shows Retry; the app and other tabs stay usable

**Exit Criteria**:
- [ ] **Unit tests**: backoff schedule (incl. 30 s for attempts > 5), cancel, exhausted retries
  emit `connection_failed` (US-019, US-020)
- [ ] **Robustness**: 100 scripted drops of 1–60 s (`docker pause` + firewall black-hole), two
  streams from one server → 0 crashes, position resumes (NFR-005); CI runs 5 iterations
- [ ] **Robustness**: outage outlasting all retries → banner within 4 min, Retry resumes at the
  banner position (US-020)

### REQ-003: Precise playback and frame navigation (Must Have)
- **Outcome**: Exact playback speeds and frame-exact stepping and skipping, with the current
  frame always visible.
- **Traces**: FR-008, FR-009, FR-011, FR-012, FR-013, FR-014, NFR-008
- **Est. AI**: 04:30

#### Milestone M-003.1: Exact playback speeds
- **Problem solved**: Review at specific speeds isn't possible.
- **Traces**: FR-008, FR-009
- **Est. AI**: 01:10

##### FEAT-003.1.1: Speed presets and fine steps
- **Est. AI**: 00:55

- **US-021** — **As a** reviewer **I want** speed presets 0.25×, 0.5×, 0.67×, 1.0×, 2.0×, 4.0×
  **So that** I can switch to a standard speed in one action (`Est. AI: 00:20`)
  - [ ] Each preset sets exactly that speed; the current speed is always displayed
- **US-022** — **As a** reviewer **I want** to raise or lower speed in fine steps **So that** I
  can pick any speed in between (`Est. AI: 00:25`)
  - [ ] Step default 0.05×, configurable (`speed_step`); speed stays within 0.05×–8.0×
  - [ ] A reset-to-1.0× action exists

**Exit Criteria**:
- [ ] **Unit tests**: speed clamping and step arithmetic (no float drift: 1.0 + 20 × 0.05 = 2.0)
- [ ] **Integration tests**: each preset and step reflected in mpv `speed` (US-021, US-022)

#### Milestone M-003.2: Frame-accurate navigation
- **Problem solved**: Reviewers can't land on, or identify, an exact frame.
- **Traces**: FR-011, FR-012, FR-013, FR-014, NFR-008
- **Est. AI**: 03:20

##### FEAT-003.2.1: Single-frame step
- **Est. AI**: 01:05

- **US-023** — **As a** reviewer **I want** to step forward one frame **So that** I can inspect
  motion precisely (`Est. AI: 00:25`)
  - [ ] If playing, the video pauses first, then advances exactly one frame (FR-011)
- **US-024** — **As a** reviewer **I want** to step back one frame **So that** I can revisit the
  previous frame (`Est. AI: 00:30`)
  - [ ] Lands on the exact previous frame in 100% of CFR test clips (NFR-008)
  - [ ] Local back-step p95 < 300 ms for GOP ≤ 250; remote back-step served from the back-buffer
    (slower when re-fetching, accepted)

##### FEAT-003.2.2: n-frame skip
- **Est. AI**: 01:25

- **US-025** — **As a** reviewer **I want** to skip n frames forward or back **So that** I move in
  precise larger jumps (`Est. AI: 00:35`)
  - [ ] n configurable (`skip_frames`, default 10, range 2–1000)
  - [ ] On CFR files with correct metadata, lands exactly n frames away in one seek; skipping
    back from frame < n lands on frame 0; skipping past the end lands on the last frame
- **US-026** — **As a** reviewer **I want** skips to stay exact when the frame rate is unknown or
  variable **So that** I never land on the wrong frame silently (`Est. AI: 00:40`)
  - [ ] With unknown fps or the VFR mark set, ±n runs as n queued single steps showing
    "Skipping i/n"
  - [ ] Any other playback command cancels the queue; at either end of the file it stops with
    "Skipped i/n"

##### FEAT-003.2.3: Position display
- **Est. AI**: 00:35

- **US-027** — **As a** reviewer **I want** to see the frame number, timestamp and duration **So
  that** I always know exactly where I am (`Est. AI: 00:25`)
  - [ ] Shows `HH:MM:SS.mmm`, total duration, and frame number = round(time-pos × fps)
  - [ ] VFR files show "≈ f <n>"; unknown fps shows "f —"

**Exit Criteria**:
- [ ] **Integration tests**: frame-accuracy test on generated CFR clips (H.264/HEVC/VP9/AV1;
  25/29.97/60 fps; GOP 250; non-zero start PTS) checked against burned-in frame indices
  (US-023…US-025)
- [ ] **Integration tests**: VFR / fallback test — VFR label, queued skip exact, cancel, boundary
  "Skipped 3/10" (US-026, US-027)
- [ ] **Performance**: local back-step p95 < 300 ms on 4K HEVC GOP 250 (NFR-008)

### REQ-004: Native-resolution snapshot (Must Have)
- **Outcome**: The current frame is saved at its native resolution as PNG or JPEG in one action.
- **Traces**: FR-018, FR-019
- **Est. AI**: 01:20

#### Milestone M-004.1: Capture the current frame
- **Problem solved**: Saving a frame as evidence needs screen capture tools that scale or add
  overlays.
- **Est. AI**: 01:20

##### FEAT-004.1.1: Snapshot capture
mpv `screenshot-to-file … video` (no OSD, no subtitles, no scaling).
- **Est. AI**: 01:05

- **US-028** — **As a** reviewer **I want** to quick-save the current frame **So that** I capture
  evidence without breaking my flow (`Est. AI: 00:30`)
  - [ ] Saves a PNG (default format) to the default folder (`<Pictures>/vplayer`, configurable)
  - [ ] Image size equals the video's native size; no OSD or overlays
  - [ ] A toast shows the saved path; existing files are never overwritten
- **US-029** — **As a** reviewer **I want** a "Save As" snapshot **So that** I choose the folder,
  name and PNG or JPEG (`Est. AI: 00:25`)
  - [ ] Format follows the chosen extension (`.png` / `.jpg`); JPEG quality setting (default 90)
  - [ ] Cancelling the dialog saves nothing

**Exit Criteria**:
- [ ] **Integration tests**: snapshot native resolution test (PNG size == video size, no overlay)
  (US-028)
- [ ] **Integration tests**: Save As PNG and JPEG; no-overwrite check (US-028, US-029)

### REQ-005: Dual control scheme (Must Have)
- **Outcome**: Every action works from a visible control and from a keyboard shortcut the user
  can rebind.
- **Traces**: FR-022, FR-023, NFR-009, NFR-011
- **Est. AI**: 02:55

#### Milestone M-005.1: Every action has a control and a shortcut
- **Problem solved**: Some actions are mouse-only or keyboard-only.
- **Traces**: FR-022, NFR-009, NFR-011
- **Est. AI**: 01:35

##### FEAT-005.1.1: Action registry
One registry of `QAction`s drives toolbar buttons, menus and shortcuts (technical design §6
action table).
- **Est. AI**: 01:20

- **US-030** — **As a** user **I want** every action on a toolbar/menu control and a shortcut **So
  that** I can use mouse or keyboard freely (`Est. AI: 00:40`)
  - [ ] Covers play/pause, speed, frame step, skip, seek, snapshot, volume, mute, fullscreen, open,
    connect, tab/window and compare actions
  - [ ] An automated check fails if any registered action lacks a visible control or a shortcut
  - [ ] UI action → visible acknowledgement p95 < 100 ms (NFR-009)
- **US-031** — **As a** keyboard user **I want** full keyboard operation and accessible names **So
  that** I never need the mouse (`Est. AI: 00:30`)
  - [ ] All controls reachable by Tab, with visible focus; every control has an accessible name
    (NFR-011)

**Exit Criteria**:
- [ ] **Unit tests**: registry parity check (action ↔ control ↔ shortcut) passes (US-030)
- [ ] **Performance**: input latency p95 < 100 ms (NFR-009)
- [ ] **Accessibility**: keyboard-only walkthrough of every action; accessible names present
  (NFR-011, WCAG 2.2 AA where applicable)

#### Milestone M-005.2: Rebind shortcuts
- **Problem solved**: Default keys don't match personal habits.
- **Traces**: FR-023
- **Est. AI**: 01:20

##### FEAT-005.2.1: Shortcut editor
Preferences → Shortcuts.
- **Est. AI**: 01:05

- **US-032** — **As a** user **I want** to rebind any shortcut with conflict detection **So
  that** I never create clashing keys (`Est. AI: 00:35`)
  - [ ] Assigning a key in use names the other action and offers to swap
  - [ ] A shortcut can never be left empty
- **US-033** — **As a** user **I want** my bindings saved and resettable **So that** they survive
  restarts and I can undo mistakes (`Est. AI: 00:20`)
  - [ ] Bindings persist across restarts; "Reset to defaults" per action and for all

**Exit Criteria**:
- [ ] **Unit tests**: conflict detection, swap, empty-binding rejection, persistence round-trip
  (US-032, US-033)
- [ ] **Integration tests**: rebind "Step back 1 frame" to `A` → swap prompt → works after
  restart (discovery §6 scenario)

### REQ-006: Tabs and windows (Must Have)
- **Outcome**: Several videos are open at once in tabs and windows, each with its own state, and
  files opened from outside join the running app.
- **Traces**: FR-035, FR-036, FR-037, FR-038, FR-040, FR-041, FR-042, FR-043 (CLI + in-app)
- **Est. AI**: 05:20

#### Milestone M-006.1: Multiple videos in tabs
- **Problem solved**: Only one video can be open at a time.
- **Traces**: FR-035, FR-037, FR-038 (tab actions), FR-040
- **Est. AI**: 01:40

##### FEAT-006.1.1: Tabbed player
- **Est. AI**: 01:25

- **US-034** — **As a** reviewer **I want** to open, close and switch tabs **So that** I keep
  several videos ready (`Est. AI: 00:40`)
  - [ ] New tab, close tab, next/previous tab actions, each with control + shortcut
  - [ ] Each tab keeps its own position, speed, volume and tracks
  - [ ] Closing the last tab leaves an empty placeholder window
- **US-035** — **As a** reviewer **I want** actions to apply only to the active tab **So that** I
  never change the wrong video (`Est. AI: 00:20`)
  - [ ] Shortcuts and toolbar actions target the active tab of the focused window only
- **US-036** — **As a** reviewer **I want** a clear message at 4 tabs **So that** I understand
  the limit (`Est. AI: 00:15`)
  - [ ] A 5th tab in a window is refused with a message; a compare tab counts as one tab

**Exit Criteria**:
- [ ] **Integration tests**: independent state per tab; action routing to active tab; 4-tab limit
  (US-034…US-036)

#### Milestone M-006.2: Multiple windows and moving tabs
- **Problem solved**: All videos are stuck in one window.
- **Traces**: FR-036, FR-038 (new window), FR-041
- **Est. AI**: 02:00

##### FEAT-006.2.1: Multiple windows
- **Est. AI**: 00:35

- **US-037** — **As a** reviewer **I want** to open new windows with their own tabs **So that** I
  can arrange videos side by side on screen (`Est. AI: 00:25`)
  - [ ] New-window action (control + shortcut); no cap on window count; each window has up to 4
    tabs

##### FEAT-006.2.2: Tab move between windows
- **Est. AI**: 01:10

- **US-038** — **As a** reviewer **I want** to drag a tab out or into another window **So that**
  I can reorganise without losing my place (`Est. AI: 00:45`)
  - [ ] Position, pause state, speed, volume and tracks are kept; no reload
  - [ ] Dropping onto a window with 4 tabs is refused with the limit message
  - [ ] Moving a window's only tab closes the emptied window unless it is the only window
- **US-039** — **As a** keyboard user **I want** "Move tab to new window" (Ctrl+Shift+N) **So
  that** I can move tabs without dragging (`Est. AI: 00:15`)
  - [ ] Moves the active tab to a new window with the same state

**Exit Criteria**:
- [ ] **Integration tests**: tab move keeps state (render context freed and recreated, no
  reload) (US-038, US-039)
- [ ] **Manual / UAT**: drag tabs between windows on Windows, Ubuntu X11 and Wayland

#### Milestone M-006.3: External opens join the running app
- **Problem solved**: Opening a file from outside starts a second app or replaces what's playing.
- **Traces**: FR-042, FR-043 (CLI flag, in-app browsers, `open_file_new_window`)
- **Est. AI**: 01:40

##### FEAT-006.3.1: Single-instance routing
`QLocalServer` + `QLockFile`; a second launch forwards its files and exits (technical design
§4.5).
- **Est. AI**: 00:50

- **US-040** — **As a** user **I want** files opened via "Open with" or the CLI to become new
  tabs **So that** the video I'm watching isn't replaced (`Est. AI: 00:40`)
  - [ ] While the app runs, a new file opens as a new tab in the last-used window; if that window
    has 4 tabs, in a new window
  - [ ] With no app running, it starts and plays the file

##### FEAT-006.3.2: Open in new window
- **Est. AI**: 00:35

- **US-041** — **As a** user **I want** an explicit "Open in new window" **So that** I choose a
  fresh window when I want one (`Est. AI: 00:25`)
  - [ ] `vplayer --new-window FILE…`, the browsers' "Open in new window" item, and the
    `open_file_new_window` action (Ctrl+Alt+O) each open in a new window

**Exit Criteria**:
- [ ] **Integration tests**: second-instance forwarding, last-used window, 4-tab overflow,
  `--new-window` (US-040, US-041)
- [ ] **Unit tests**: IPC message validation (malformed messages ignored)

### REQ-007: Synced compare (Must Have)
- **Outcome**: Two videos with the same frame rate play side by side in one tab, moving together,
  with an adjustable offset.
- **Traces**: FR-044, FR-045, FR-046, FR-048, NFR-008 (compare)
- **Est. AI**: 04:15

#### Milestone M-007.1: Open two videos side by side safely
- **Problem solved**: There's no way to view two recordings together, and comparing different
  frame rates would mislead.
- **Traces**: FR-044, FR-048
- **Est. AI**: 01:25

##### FEAT-007.1.1: Compare view
- **Est. AI**: 01:10

- **US-042** — **As a** reviewer **I want** "Compare with…" (pick a file) and "Compare tabs"
  (pick an open tab) **So that** two videos appear side by side (`Est. AI: 00:40`)
  - [ ] Opens one compare tab with A and B panes; it counts as one tab (AD-017)
  - [ ] Compare actions are disabled when the active tab is already a compare tab
  - [ ] Works with any mix of local and SFTP files
- **US-043** — **As a** reviewer **I want** mismatched frame rates refused **So that** I never
  compare misaligned frames (`Est. AI: 00:20`)
  - [ ] Rates must match within 0.001 fps (29.97 = 30000/1001; 29.97 ≠ 30); otherwise an error
    shows both rates and nothing changes
  - [ ] Unknown fps is refused with "Frame rate unknown"

**Exit Criteria**:
- [ ] **Unit tests**: fps comparison (tolerance, unknown) (US-043)
- [ ] **Integration tests**: both entry paths open a compare tab; mismatch leaves tabs unchanged
  (US-042, US-043)

#### Milestone M-007.2: Drive both videos together
- **Problem solved**: Controlling two players separately loses alignment.
- **Traces**: FR-045, FR-046, NFR-008 (compare)
- **Est. AI**: 02:50

##### FEAT-007.2.1: Synced transport
A is master; B follows with drift correction (technical design §4.4).
- **Est. AI**: 01:25

- **US-044** — **As a** reviewer **I want** play/pause, seek, speed, frame step and ±n skip to
  move both videos **So that** they stay aligned (`Est. AI: 00:45`)
  - [ ] With sync on, every one of these actions applies to both sides
  - [ ] On CFR files both sides land on the target frame after a step or skip (NFR-008)
  - [ ] Drift > max(2 frames, 100 ms) on two samples in a row is corrected
- **US-045** — **As a** reviewer **I want** sensible behaviour when one video is shorter or
  offset **So that** nothing jumps unexpectedly (`Est. AI: 00:30`)
  - [ ] When A's position maps outside B, B is held paused at its nearest end and rejoins when
    back in range
  - [ ] When A reaches its end, B pauses too

##### FEAT-007.2.2: Offset and sync toggle
- **Est. AI**: 01:10

- **US-046** — **As a** reviewer **I want** to set an offset in time or frames **So that** I can
  align recordings that started at different times (`Est. AI: 00:30`)
  - [ ] Offset set in a seconds spin box with ±1 frame buttons (`offset_plus_frame` /
    `offset_minus_frame`, Alt+. / Alt+,); always rounded to whole frames
  - [ ] Editing the offset with sync on pauses both, realigns B, and resumes if they were playing
- **US-047** — **As a** reviewer **I want** to turn sync off and adjust one side alone **So that**
  I can nudge a single video (`Est. AI: 00:30`)
  - [ ] Sync toggle (Ctrl+L); with sync off, playback commands go only to the active side
  - [ ] Active side switches by clicking a pane or `compare_switch_side` (Ctrl+;), with a visible
    focus border
  - [ ] Turning sync back on pauses both sides and keeps them paused

**Exit Criteria**:
- [ ] **Integration tests**: compare frame-accuracy on CFR clips — both sides on target frame
  after steps, skips and seeks (US-044, NFR-008)
- [ ] **Integration tests**: out-of-range hold, A EOF pauses B, offset edit realigns, sync
  off/on rules (US-045…US-047)
- [ ] **Manual / UAT**: discovery §6 "Synced compare" scenario (2.4 s offset, local + remote)

### REQ-008: Packaging and OS integration (Must Have)
- **Outcome**: One-step per-user install on Windows and Ubuntu with PATH (Windows), desktop
  entry, icon and "Open with"; uninstall leaves nothing behind.
- **Traces**: FR-029, FR-030, FR-031, FR-043 (OS context menu), NFR-012, NFR-013, NFR-014
- **Est. AI**: 03:25

#### Milestone M-008.1: Windows installer
- **Problem solved**: Windows setup is manual with no PATH or "Open with".
- **Traces**: FR-029, FR-031 (Windows), FR-043 (Windows), NFR-013
- **Est. AI**: 02:00

##### FEAT-008.1.1: PyInstaller bundle + Inno Setup installer
- **Est. AI**: 01:45

- **US-048** — **As an** installer **I want** a per-user install that adds the app to PATH by
  default **So that** I can run `vplayer` from any terminal (`Est. AI: 00:40`)
  - [ ] Installs to `%LOCALAPPDATA%\Programs\VPlayer` without admin rights; installer < 120 MB
    (NFR-013)
  - [ ] PATH checkbox default on; unchecked → no PATH entry; unchecking on upgrade removes only the
    entry this installer added
- **US-049** — **As a** user **I want** "Open with VPlayer" and "Open in new VPlayer window" on
  media files **So that** I open videos from Explorer (`Est. AI: 00:30`)
  - [ ] Registered for mp4, mkv, webm, mov, avi, ts, m4v, wmv, flv, mpg, mpeg without taking over
    the default app
- **US-050** — **As an** installer **I want** a clean uninstall **So that** nothing is left behind
  (`Est. AI: 00:25`)
  - [ ] Removes associations, shortcuts and the PATH entry it added; other PATH entries and a
    pre-existing app entry are left intact

**Exit Criteria**:
- [ ] **Manual / UAT**: Windows packaging smoke checklist on Windows 10 22H2 and Windows 11
  (fresh PATH on/off, upgrade on→off, local + SFTP playback, both context-menu entries,
  uninstall) (US-048…US-050)
- [ ] **Performance**: installer size < 120 MB (NFR-013)

#### Milestone M-008.2: Ubuntu install
- **Problem solved**: Ubuntu setup is manual with no menu entry or "Open With".
- **Traces**: FR-030, FR-031 (Linux), FR-043 (Linux)
- **Est. AI**: 01:25

##### FEAT-008.2.1: AppImage + `install.sh`
- **Est. AI**: 01:10

- **US-051** — **As an** installer **I want** a desktop entry, icon and MIME associations **So
  that** VPlayer appears in the app menu and "Open With" (`Est. AI: 00:40`)
  - [ ] `install.sh` installs the AppImage, `.desktop` entries (normal + "new window") with
    absolute `Exec` paths, icon and MIME types, and refreshes the desktop database
  - [ ] Runs on Ubuntu 22.04 X11 and Wayland; the `libxcb-cursor0` prerequisite (missing on stock
    22.04) is listed in the setup instructions
- **US-052** — **As an** installer **I want** `install.sh --uninstall` **So that** everything it
  added is removed (`Est. AI: 00:20`)
  - [ ] Removes the AppImage, desktop entries, icon and MIME registrations

**Exit Criteria**:
- [ ] **Manual / UAT**: Ubuntu packaging smoke on X11 and Wayland — install, Open With (both
  entries), local + SFTP playback, uninstall (US-051, US-052)

### REQ-009: Long-run stability and memory (Must Have)
- **Outcome**: Memory stays within limits with many tabs and over many hours, and the app never
  crashes.
- **Traces**: NFR-001, NFR-002
- **Est. AI**: 02:15

#### Milestone M-009.1: Bounded memory with many tabs
- **Problem solved**: Each open tab keeps a full decoder and buffers in memory.
- **Traces**: NFR-001
- **Est. AI**: 01:10

##### FEAT-009.1.1: Background tab suspension
A tab hidden for 60 s unloads its video and keeps a suspend record (AD-019).
- **Est. AI**: 00:55

- **US-053** — **As a** reviewer **I want** hidden tabs to release memory and come back exactly as
  I left them **So that** many tabs don't exhaust memory (`Est. AI: 00:45`)
  - [ ] A tab hidden for 60 s is suspended; each suspended tab adds < 60 MiB RSS
  - [ ] On show it reloads at the saved position, speed, volume, tracks, external subtitles and
    play/pause state
  - [ ] One 4K HEVC video: RSS < 250 MiB (SFTP: plus its buffer caps)

**Exit Criteria**:
- [ ] **Integration tests**: background suspend/resume test (waits 70 s) restores full state
  (US-053)
- [ ] **Performance**: memory test, 2 windows × 4 tabs workload, per-tab increment and
  compare-tab suspended memory within NFR-001

#### Milestone M-009.2: Stable over long sessions
- **Problem solved**: Long reviews leak memory or crash.
- **Traces**: NFR-002 (and re-verifies NFR-004/005 on the release build)
- **Est. AI**: 01:05

##### FEAT-009.2.1: Soak and error containment
- **Est. AI**: 00:50

- **US-054** — **As a** reviewer **I want** the player to run all day without growing or crashing
  **So that** I can trust it for long files (`Est. AI: 00:40`)
  - [ ] RSS growth < 5% over 8 h continuous playback; 24 h soak with no crash (local and SFTP)
  - [ ] Unhandled exceptions are caught, logged and shown; they never terminate the app

**Exit Criteria**:
- [ ] **Performance**: 8 h soak growth < 5%, 24 h soak no crash, on the release builds (US-054)
- [ ] **Robustness**: corrupt corpus and 100-drop network test re-run on the release builds
  (NFR-004/005)

### REQ-010: Review conveniences (Should Have)
- **Outcome**: Captures and positions are traceable, tracks and subtitles are selectable, pitch
  is preserved, and shortcuts are discoverable.
- **Traces**: FR-010, FR-020, FR-024, FR-027, FR-050
- **Est. AI**: 03:15

#### Milestone M-010.1: Traceable captures and positions
- **Problem solved**: Snapshots and noted positions can't be traced back to the exact frame.
- **Traces**: FR-020, FR-050
- **Est. AI**: 01:10

##### FEAT-010.1.1: Snapshot naming
- **Est. AI**: 00:30

- **US-055** — **As a** reviewer **I want** quick-saved snapshots named after source, time and
  frame **So that** I can trace each image (`Est. AI: 00:20`)
  - [ ] Name is `<source>_<HH-MM-SS.mmm>_f<frame>.png`; `_f<frame>` omitted when fps is unknown
  - [ ] Source name is sanitized (no path separators/control characters, ≤ 120 chars); an
    existing file is never overwritten

##### FEAT-010.1.2: Copy position
- **Est. AI**: 00:25

- **US-056** — **As a** reviewer **I want** to copy the current position **So that** I can paste
  it into notes (`Est. AI: 00:15`)
  - [ ] Copies e.g. `00:12:34.567 f22213` from a control and a shortcut; only the timestamp when
    fps is unknown

**Exit Criteria**:
- [ ] **Unit tests**: snapshot naming and clipboard format, incl. unknown fps and collisions
  (US-055, US-056)

#### Milestone M-010.2: Audio and subtitle control
- **Problem solved**: Multi-track and subtitled files can't be reviewed properly.
- **Traces**: FR-010, FR-027
- **Est. AI**: 01:25

##### FEAT-010.2.1: Tracks and subtitles
- **Est. AI**: 00:45

- **US-057** — **As a** reviewer **I want** to choose audio and subtitle tracks and load an
  external subtitle file **So that** I hear and read the right track (`Est. AI: 00:35`)
  - [ ] Track menus list all embedded tracks; cycle actions with shortcuts
  - [ ] External subtitle file (local or from the same SFTP server) loads and survives tab
    suspend/resume

##### FEAT-010.2.2: Pitch correction
- **Est. AI**: 00:25

- **US-058** — **As a** reviewer **I want** pitch preserved at non-1.0 speeds, with an option to
  turn it off **So that** speech stays intelligible (`Est. AI: 00:15`)
  - [ ] Pitch correction on by default; setting toggles it

**Exit Criteria**:
- [ ] **Integration tests**: track selection, external subtitle load and re-add after resume,
  pitch setting reflected in mpv (US-057, US-058)

#### Milestone M-010.3: Discoverable shortcuts
- **Problem solved**: Users can't see which key triggers an action.
- **Traces**: FR-024
- **Est. AI**: 00:40

##### FEAT-010.3.1: Shortcut hints
- **Est. AI**: 00:25

- **US-059** — **As a** user **I want** tooltips and menus to show each action's current shortcut
  **So that** I learn the keys (`Est. AI: 00:15`)
  - [ ] Tooltip and menu text show the current binding and update right after a rebind

**Exit Criteria**:
- [ ] **Integration tests**: rebind → tooltip/menu text updated (US-059)

### REQ-011: Saved connections (Should Have)
- **Outcome**: Recent files and SSH servers are one click away, using saved profiles or
  `~/.ssh/config` aliases.
- **Traces**: FR-028, FR-051
- **Est. AI**: 01:40

#### Milestone M-011.1: Reconnect without retyping
- **Problem solved**: Host, user and key must be re-entered for every connection.
- **Est. AI**: 01:40

##### FEAT-011.1.1: Recent files and connection profiles
- **Est. AI**: 00:45

- **US-060** — **As a** reviewer **I want** recent files and saved connection profiles **So
  that** I reopen work quickly (`Est. AI: 00:35`)
  - [ ] Recent files list (local and SFTP) in the File menu; saved profiles in the connect dialog
  - [ ] Secrets are stored only in the OS keyring; settings never contain passwords or
    passphrases

##### FEAT-011.1.2: `~/.ssh/config` aliases
- **Est. AI**: 00:40

- **US-061** — **As a** reviewer **I want** to type a `Host` alias from `~/.ssh/config` **So
  that** I reuse my SSH setup (`Est. AI: 00:30`)
  - [ ] HostName, Port, User and IdentityFile are filled from the alias
  - [ ] Other directives (e.g. ProxyJump) are ignored and listed by name in a visible notice;
    `Match exec` blocks are skipped and never run
  - [ ] A missing config is ignored; an unreadable one shows a notice

**Exit Criteria**:
- [ ] **Unit tests**: ssh config alias resolution (override, ProxyJump notice, missing file,
  `Match exec` skipped, Canonical* lines dropped, parse error) (US-061)
- [ ] **Security**: no secrets in settings files after saving a profile (US-060)

### REQ-012: Background tab playback policy (Should Have)
- **Outcome**: Tabs that aren't visible pause by default; the user can choose to keep them
  playing.
- **Traces**: FR-039
- **Est. AI**: 00:55

#### Milestone M-012.1: Hidden tabs don't play unexpectedly
- **Problem solved**: Background tabs keep playing audio and using CPU.
- **Est. AI**: 00:55

##### FEAT-012.1.1: Background tab setting
- **Est. AI**: 00:40

- **US-062** — **As a** reviewer **I want** hidden tabs to auto-pause, with an option to keep
  playing **So that** only what I'm watching plays (`Est. AI: 00:30`)
  - [ ] `background_tabs` setting: `pause` (default), `muted`, `play`
  - [ ] A tab counts as hidden when it isn't the current tab or its window is minimized (on
    Wayland, only non-current tabs count)
  - [ ] When the tab is shown again, it resumes only if it was playing before it was hidden

**Exit Criteria**:
- [ ] **Integration tests**: each setting value on tab switch and minimize (X11/Windows)
  (US-062)

### REQ-013: Compare extras (Should Have)
- **Outcome**: Compare view captures both sides and shows each side's streaming health.
- **Traces**: FR-047, FR-049
- **Est. AI**: 01:15

#### Milestone M-013.1: Inspect both sides in compare
- **Problem solved**: In compare view, evidence and streaming status are available for one side
  only.
- **Est. AI**: 01:15

##### FEAT-013.1.1: Compare snapshot
- **Est. AI**: 00:30

- **US-063** — **As a** reviewer **I want** to snapshot the active side or both sides **So that**
  I capture matching evidence (`Est. AI: 00:20`)
  - [ ] "Both" saves two PNGs at each side's native resolution

##### FEAT-013.1.2: Buffer health per side
- **Est. AI**: 00:30

- **US-064** — **As a** reviewer **I want** each SFTP side's buffer health shown **So that** I
  know why one side stalls (`Est. AI: 00:20`)
  - [ ] Each SFTP pane shows buffered seconds ahead; local panes show nothing

**Exit Criteria**:
- [ ] **Integration tests**: both-sides snapshot produces two native-size PNGs (US-063); buffer
  indicator updates during SFTP play (US-064)

### REQ-014: Resume local files (Could Have)
- **Outcome**: Reopening a local file continues where the user left off.
- **Traces**: FR-032
- **Est. AI**: 00:50

#### Milestone M-014.1: Resume from last position
- **Problem solved**: Long files always restart from the beginning.
- **Est. AI**: 00:50

##### FEAT-014.1.1: Resume position
- **Est. AI**: 00:35

- **US-065** — **As a** reviewer **I want** local files to reopen at the last position **So
  that** I continue long reviews (`Est. AI: 00:25`)
  - [ ] Position stored per local file on close; reopening offers or applies resume; setting to
    disable

**Exit Criteria**:
- [ ] **Integration tests**: close → reopen resumes within one keyframe (US-065)

### REQ-015: A-B loop (Could Have)
- **Outcome**: A chosen segment repeats until the loop is cleared.
- **Traces**: FR-033
- **Est. AI**: 00:55

#### Milestone M-015.1: Loop a segment
- **Problem solved**: Re-watching a short segment needs repeated manual seeks.
- **Est. AI**: 00:55

##### FEAT-015.1.1: A-B loop
- **Est. AI**: 00:40

- **US-066** — **As a** reviewer **I want** to set A and B points and loop between them **So
  that** I review a segment repeatedly (`Est. AI: 00:30`)
  - [ ] Set A, set B, clear loop actions (control + shortcut); loop shown on the seek bar

**Exit Criteria**:
- [ ] **Integration tests**: playback loops between A and B; clear stops looping (US-066)

## 6. User Experience
### Entry Points
- OS "Open with VPlayer" / "Open in new VPlayer window" on media files (Windows, Ubuntu).
- `vplayer [--new-window] FILE|sftp://URI…` from any terminal.
- App menu / Start menu entry → empty window with File → Open, Connect to server, and the local
  browser dock.

### Core Experience
| Step | Action | System Response | Success State |
|------|--------|-----------------|---------------|
| 1 | Open local file (dialog, browser, Open with, CLI) | Plays in a tab of the last-used window | First frame < 1.5 s |
| 2 | Connect to server (host or ssh alias, auth) | Host key check, remote browser opens | Connected; key trusted |
| 3 | Pick a remote file | Streams into a tab, RAM only | First frame < 3 s; 0 bytes on disk |
| 4 | Pause, step ±1, skip ±n, change speed | Exact frame/speed; position display updates | Lands on intended frame |
| 5 | Snapshot | PNG at native resolution, toast with path | File saved, never overwritten |
| 6 | Compare with / Compare tabs, set offset | Two panes move together | Both sides on the same target frame |
| 7 | Network drop | "Reconnecting…", then resume; or "Connection lost" + Retry | Same position after recovery |

### Edge Cases
| Case | Behaviour |
|------|-----------|
| 5th tab in a window | Refused with a message; Open with/CLI overflows to a new window |
| Compare with different frame rates | Refused; error shows both rates; tabs unchanged |
| Unknown or variable fps | "f —" / "≈ f n"; ±n uses exact single steps |
| Changed host key | Hard warning on connect; hard failure on auto-reconnect |
| Outage longer than retries | "Connection lost at <time>" + Retry |
| Corrupt or unplayable file | Skips damaged packets or shows a banner; app stays up |
| Hidden tab | Pauses (default); suspended after 60 s; restored on show |

### Pages & Screens
Main window (tab bar, video area, transport toolbar, position display, status bar, local/remote
browser docks); compare tab (two panes, offset control, sync toggle); Connect dialog; host-key
dialog; Preferences (General, Playback, Network, Snapshot, Shortcuts); snapshot "Save As" dialog.
Details: technical design §7.

## 7. Technical Considerations
- **Stack**: Python 3.12, PySide6, libmpv (python-mpv 1.0.8; Ubuntu `libmpv1` 0.34.1; pinned
  Windows `libmpv-2.dll`), Paramiko 5.x, keyring; PyInstaller + Inno Setup 6 (Windows),
  AppImage + `install.sh` (Ubuntu). Rust only if a requirement can't be met in Python.
- **Integration points**: OpenSSH SFTP servers (8.x/9.x), OS keyring, `~/.ssh/known_hosts` and
  `~/.ssh/config` (read-only), Windows registry (HKCU), freedesktop desktop/MIME databases.
- **Data storage & privacy**: settings in a QSettings INI file; no media bytes ever on disk; only
  the documented app files are written (settings, app known-hosts, logs, lock/socket files);
  secrets only in the OS keyring.
- **Performance**: mpv's RAM-only demuxer cache provides read-ahead/back-buffer; background tabs
  suspend after 60 s; hardware decoding with software fallback.
- **Licensing**: GPL/LGPL components acceptable for personal use (NFR-014); re-review before any
  sharing.
- **Challenges**: tracked as spikes in technical design §13 — hwdec with the render API on
  Windows, VAAPI interop on Ubuntu 22.04, Paramiko throughput, hr-seek rounding, tab-move render
  context, installer size, hardware decoder session limits.

## 8. Success Metrics
- Disk writes during a 2 h SFTP session: 0 bytes — _Procmon / `inotifywait`_
- ±1 frame accuracy on CFR test clips: 100% — _burned-in frame index test_
- RSS, one 4K HEVC video: < 250 MiB; 8 h growth < 5% — _psutil sampling in soak test_
- Crashes: 0 over ≥ 50 corrupt files and 100 network drops — _robustness scripts_
- Cold start to first frame: < 1.5 s local; < 3 s SFTP at 50 ms RTT — _timed integration tests_
- Action parity: 100% of registry actions have a control and a shortcut — _automated check_
- Installer size: < 120 MB — _release smoke check_

## 9. Delivery Sequence
Milestones in build order. The technical design §13 spikes (hwdec/render API, VAAPI, Paramiko
throughput, hr-seek rounding, tab-move render context) run inside the first milestone that
depends on them (M-001.1, M-002.2, M-003.2, M-006.2).

| Order | Milestone | Requirement | Priority | Est. AI | Depends on | Exit criteria met |
|-------|-----------|-------------|----------|---------|------------|-------------------|
| 1 | M-001.1 Play a local file end to end | REQ-001 | Must | 03:15 | — | [ ] |
| 2 | M-005.1 Every action has a control and a shortcut | REQ-005 | Must | 01:35 | M-001.1 | [ ] |
| 3 | M-003.1 Exact playback speeds | REQ-003 | Must | 01:10 | M-005.1 | [ ] |
| 4 | M-003.2 Frame-accurate navigation | REQ-003 | Must | 03:20 | M-005.1 | [ ] |
| 5 | M-004.1 Capture the current frame | REQ-004 | Must | 01:20 | M-005.1 | [ ] |
| 6 | M-001.2 Browse local media | REQ-001 | Must | 01:20 | M-005.1 | [ ] |
| 7 | M-001.3 Survive any file | REQ-001 | Must | 01:55 | M-001.1 | [ ] |
| 8 | M-002.1 Connect securely | REQ-002 | Must | 02:30 | M-005.1 | [ ] |
| 9 | M-002.2 Stream remote files without local copies | REQ-002 | Must | 02:50 | M-002.1, M-003.2 | [ ] |
| 10 | M-002.3 Recover from network drops | REQ-002 | Must | 01:40 | M-002.2 | [ ] |
| 11 | M-006.1 Multiple videos in tabs | REQ-006 | Must | 01:40 | M-005.1 | [ ] |
| 12 | M-006.2 Multiple windows and moving tabs | REQ-006 | Must | 02:00 | M-006.1 | [ ] |
| 13 | M-006.3 External opens join the running app | REQ-006 | Must | 01:40 | M-006.1, M-001.2 | [ ] |
| 14 | M-007.1 Open two videos side by side safely | REQ-007 | Must | 01:25 | M-006.1, M-003.2 | [ ] |
| 15 | M-007.2 Drive both videos together | REQ-007 | Must | 02:50 | M-007.1 | [ ] |
| 16 | M-009.1 Bounded memory with many tabs | REQ-009 | Must | 01:10 | M-006.1 | [ ] |
| 17 | M-005.2 Rebind shortcuts | REQ-005 | Must | 01:20 | M-005.1 | [ ] |
| 18 | M-008.1 Windows installer | REQ-008 | Must | 02:00 | M-006.3 | [ ] |
| 19 | M-008.2 Ubuntu install | REQ-008 | Must | 01:25 | M-006.3 | [ ] |
| 20 | M-010.1 Traceable captures and positions | REQ-010 | Should | 01:10 | M-004.1, M-003.2 | [ ] |
| 21 | M-010.2 Audio and subtitle control | REQ-010 | Should | 01:25 | M-009.1 | [ ] |
| 22 | M-010.3 Discoverable shortcuts | REQ-010 | Should | 00:40 | M-005.2 | [ ] |
| 23 | M-011.1 Reconnect without retyping | REQ-011 | Should | 01:40 | M-002.1 | [ ] |
| 24 | M-012.1 Hidden tabs don't play unexpectedly | REQ-012 | Should | 00:55 | M-009.1 | [ ] |
| 25 | M-013.1 Inspect both sides in compare | REQ-013 | Should | 01:15 | M-007.2, M-002.2 | [ ] |
| 26 | M-009.2 Stable over long sessions (v1 release gate) | REQ-009 | Must | 01:05 | 1–25 | [ ] |
| **Total v1** | | | | **44:35** | | |
| 27 | M-014.1 Resume from last position (post-v1, optional) | REQ-014 | Could | 00:50 | M-009.2 | [ ] |
| 28 | M-015.1 Loop a segment (post-v1, optional) | REQ-015 | Could | 00:55 | M-009.2 | [ ] |
| **Total incl. Could** | | | | **46:20** | | |

## 10. Open Questions
- [x] Product name: **VPlayer** / `vplayer` (owner, 2026-10-11: "use whatever name; can change
  later"). A later rename touches installer IDs, ProgID, `.desktop` file names and settings
  paths; keep the name in one constant (`APP_NAME`) and the packaging files to make that cheap.
- [ ] Spike outcomes in technical design §13 may change estimates for M-001.1 (hwdec on Windows /
  VAAPI on Ubuntu), M-002.2 (Paramiko throughput: may trigger a targeted Rust module),
  M-003.2 (hr-seek rounding) and M-006.2 (tab-move render context).
