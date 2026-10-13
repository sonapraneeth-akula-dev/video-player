# Remaining work and blockers

Status on 2026-10-13, against the [Azure task list](plans/2026-10-11_video-player_azure-task-list.md).
The checklist has **90 completed / 22 open Tasks** and **5 completed / 4 open
Debug items**: 26 numbered rows remain open. Milestone exit criteria are
separate checkboxes and are not included in these counts. No open item below is
marked complete just because its test harness or a partial implementation exists.

GitHub Actions run `38380466187` at commit `0063d38` passed Windows and
Ubuntu, with combined line coverage of 84% and 87%, respectively (80%
required). Ubuntu tests run in bounded groups with fresh Xvfb displays and
Windows player-lifecycle tests run separately. This establishes a green CI
baseline, **not** the absence of shared-process native crashes or completion
of device-specific performance, release soak, or manual desktop checks.

## Tasks directly involving deferred SFTP work (7)

The owner's current scope instruction is to **avoid SFTP-related feature
work**. That is the immediate reason these rows remain open; it is not a
newly diagnosed SFTP transport failure. The remote browser model exists, but
`SftpDirModel` is not wired into an authenticated browser pane/session
lifecycle. Full remote browsing and selection-dependent entry points cannot
be verified until that integration exists.

| Task | Remaining work and concrete prerequisite |
|---|---|
| `2.3.1.1.3` | Build `scripts/net_drop.py` for random 1-60 s Docker pause and firewall DROP, two simultaneous streams, five CI and 100 release iterations. Deferred SFTP fault-injection work; the existing single-drop reconnect tests do not satisfy this gate. |
| `6.3.2.1.1` | Add `--new-window`, Ctrl+Alt+O, and browser context-menu opens for local **and SFTP** selections. Requires authenticated remote browser selection wiring as well as the entry points. |
| `7.1.1.1.1` | Build `CompareTab` and both creation paths, including local/SFTP mixes. Requires the remote browser/session path and an actionable compare-pane UI; the existing sync engine alone is not a compare view. |
| `9.2.1.1.1` | Run scripted 8 h local 4K and 24 h mixed local/SFTP soak with drops on release builds. Mixed remote workload and sustained release environment remain outstanding. |
| `9.2.1.1.2` | Re-run corrupt corpus and 100-drop network test on both release builds. Requires the drop harness (`2.3.1.1.3`), SFTP scope resumption, and built release artifacts. |
| `10.2.1.1.3` | Load local and same-server `vpsftp://` subtitles and restore them after resume. Depends on an authenticated remote session and tab suspension (`9.1.1.1.1`). |
| `13.1.2.1.1` | Show per-pane SFTP buffer duration, suppress the indicator on local panes. Requires compare panes (`7.1.1.1.1`) and an active SFTP stream. |

## Other open Tasks (15)

These are **not all blocked by SFTP**. "Depends on" below means an
implementation prerequisite, not a request for owner input; the foundational
registry and suspension tasks can be developed independently if prioritized.

| Task | Remaining work / blocker |
|---|---|
| `3.2.1.2.3` | Strict 50-position 4K HEVC GOP-250 back-step gate: p95 **2,004 ms** on this Hyper-V/RDP Windows host versus **<300 ms** required on both OSes. `hwdec-current=no`; forced D3D11VA/DXVA2 copy-back also fell back to software. The opt-in fixture/benchmark exists, but a representative Windows GPU and Ubuntu 22.04 desktop/GPU are unavailable here; measure and optimize before closing. Do not relax the threshold. |
| `5.1.1.1.1` | Central `ACTIONS` registry and per-window `QAction` creation for every design action ID. Foundational unfinished implementation; no external blocker. |
| `5.1.1.1.2` | Registry/control/shortcut parity, conflict and invalid-settings tests. Depends on `5.1.1.1.1`; existing hand-wired actions are not a registry. |
| `5.2.1.1.1` | Shortcut editor with named conflicts and Swap/Cancel, rejecting empty bindings. Depends on the registry. |
| `5.2.1.2.1` | PortableText binding persistence, resets and live multi-window application. Depends on the registry and editor. |
| `7.1.1.1.2` | Create compare from playing, paused and suspended tabs; replace compare on open. Depends on `CompareTab` (`7.1.1.1.1`) and suspension (`9.1.1.1.1`). |
| `7.2.1.1.3` | Swap audible compare side, exactly one side unmuted. Depends on `CompareTab`. |
| `7.2.1.2.2` | VFR compare banner and per-side queued frame skips. Depends on `CompareTab` and its existing sync-core integration. |
| `7.2.2.1.1` | Frame-rounded offset controls and synchronized pause/realign/resume. Depends on `CompareTab` and its existing sync-core integration. |
| `7.2.2.2.1` | Sync toggle and active-side focus/routing. Depends on `CompareTab` and action routing. |
| `9.1.1.1.1` | Hidden-tab 60 s suspend and full playback-state restore. Foundational unfinished implementation; requires a real 70 s integration test, not an owner decision. |
| `9.1.1.1.2` | Suspend both players in a background compare tab. Depends on suspension and `CompareTab`. |
| `9.1.1.1.3` | `scripts/memory_check.py` and RSS limits for warmed 4K, suspended tabs and two windows x four tabs. Depends on suspension; representative 4K measurements remain necessary. |
| `10.3.1.1.1` | Refresh shortcut tooltips/menus when bindings change. Depends on registry and rebind signal. |
| `13.1.1.1.1` | Capture both compare sides at their native dimensions, or the active side alone. Depends on `CompareTab`; single-player snapshots already work. |

## Open Debug items (4)

| Debug item | Evidence and required unblock |
|---|---|
| `1.1.1.2.1` | Windows 4K HEVC hardware-decoding CPU/RSS and back-step comparison under D3D11VA/DXVA2; this RDP host exposes software decoding only. Requires a representative Windows GPU and a documented render-path decision. |
| `1.1.1.2.2` | Ubuntu VAAPI zero-copy under X11 and Wayland, including Qt native-display integration. Requires the owner's Ubuntu 22.04 GPU desktop and a measured `hwdec-current=vaapi`. |
| `2.2.2.1.1` | One/two-stream Paramiko `readv` throughput against the owner's VPN. Deferred SFTP measurement; needs access to the actual VPN/link to decide whether the 25 MB/s Python threshold is met. |
| `9.2.1.1.3` | Conditional investigation only **if** the release soak shows RSS growth or a crash. No soak result yet; retain this contingency rather than reporting it as a known soak failure. |

**Other release gates remain separate:** the emulated SFTP first-frame
criterion (<3 s) has exceeded its limit on some Windows runs (for example
4.527 s), despite an earlier green Ubuntu netem run. Previous long-lived
pytest/Xvfb processes stalled or segfaulted at varying native playback tests;
process isolation keeps CI bounded but has not established that native root
cause. Interactive Windows/Ubuntu X11/Wayland UAT, release soak, and
device-specific hardware-decoding validation remain outstanding. Consult
[crash history](CRASHES.md) and [setup and CI details](SETUP.md); do not infer
those acceptance gates from a green hosted run.
