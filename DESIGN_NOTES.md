# Design and maintenance notes for AI-assisted refinement

## Purpose

Provide a maintainable Tkinter application that displays a selectable subset
of Reolink NVR channels. Keep device credentials out of source/config files,
keep blocking media/network work away from Tk's event loop, and isolate
protocol-specific code so later changes do not require rewriting the GUI.

## Package map

- `main.py`: startup orchestration, YAML load, KeePassXC password retrieval,
  API login, channel discovery, application launch.
- `reolink_viewer/config.py`: YAML parsing and path normalization.
- `reolink_viewer/credentials.py`: KeePassXC CLI integration. The only
  component that knows how passwords are retrieved.
- `reolink_viewer/reolink_api.py`: HTTP CGI login, channel inventory, and
  spotlight control.
- `reolink_viewer/video.py`: one RTSP/OpenCV worker per visible channel.
- `reolink_viewer/talkback.py`: microphone capture and configurable talkback
  CLI adapter.
- `reolink_viewer/layout.py`: JSON layout persistence.
- `reolink_viewer/gui.py`: Tk widgets, user actions, refresh loop, and lifecycle.

## Threading model

Tkinter is single-threaded. Never call Tk widget methods from worker threads.
`CameraStream` owns a daemon thread that reads RTSP frames and publishes the
latest frame behind a lock. The Tk `after()` loop fetches the most recent frame
and paints it. This is a latest-frame strategy: intermediate frames are
intentionally discarded rather than allowing an unbounded queue to build up.

Spotlight CGI calls run in a worker thread to avoid freezing the interface.
Results are marshalled to Tk with `after()`. Talkback audio capture runs in the
PortAudio callback and writes PCM to a subprocess pipe; stop/close it when the
mouse button is released or the pane closes.

## Channel numbering

Reolink CGI channel indexes are zero-based. RTSP path channel identifiers are
one-based and two-digit padded. `channel["index"]` is used for CGI and
`channel["rtsp_channel"]` for RTSP. User config `excluded_channels` and
`channels` keys use one-based RTSP channel numbers. Pane/layout identifiers
combine the internal index and stream name so one camera can have main and sub
panes simultaneously.

## Video design

Use Reolink's `Preview_NN_main` or `Preview_NN_sub` path. The substream is the
default because an NVR can expose many channels and decoding all main streams
can consume substantial CPU and network bandwidth. Use main stream for a
single selected channel or high-detail inspection. OpenCV's FFmpeg backend
decodes RTSP; no video transcoding or recording is performed by this app.

The stream worker reconnects after failures and stores only one latest frame.
A production refinement should add explicit FFmpeg read/open timeout options,
per-stream logging, and bounded shutdown handling. Never log RTSP URLs because
they contain credentials.

## Layout persistence

`LayoutStore` writes JSON atomically through a temporary file and rename.
Saved state includes:
- Tk main-window geometry string;
- visible pane identities and order (channel index plus stream type);
- each pane's row, column, width, and height;
- chosen number of columns.

The GUI uses nested `ttk.Panedwindow` widgets: a vertical splitter divides
rows, and each row has a horizontal splitter dividing camera panes. Users can
drag splitters to resize individual tiles. Pane dimensions and row/column
ordering are persisted; restoration replays cumulative sash positions after
Tk assigns initial geometry. If future layouts support arbitrary tile trees,
persist a normalized splitter tree rather than only row/column coordinates.

## Credentials and security

The YAML file stores only KeePassXC database path and entry locator, never the
NVR password. `keepassxc-cli show -s -a password` retrieves the entry secret.
The password exists in memory and is passed to RTSP and CGI clients. Do not
include it in exceptions, logs, process arguments, or persisted state.
Protect `config.yaml` and layout files with user-only permissions. RTSP embeds
credentials in its URL; avoid printing/logging that URL. Consider a dedicated
least-privilege NVR account and HTTPS for CGI.

## Reolink API details

- Login: `POST /api.cgi?cmd=Login&token=null`, JSON body with `User.userName`
  and `User.password`. Subsequent CGI requests include `token=...`.
- Inventory: `GetChannelstatus`. The response `value.status` array contains
  channel entries. The index in that array is the zero-based channel index.
- Spotlight: `GetWhiteLed` for the selected zero-based channel, then
  `SetWhiteLed` with the returned `WhiteLed` object after changing `state`.
  Preserve other fields; spotlight availability depends on camera model.
- `Logout` is called during orderly application shutdown.

Check actual NVR firmware responses before changing request shapes. Reolink
CGI schemas and supported fields can vary by hardware/firmware.

## Two-way audio design

RTSP is a video/audio receive stream, not a Reolink talkback transport.
Reolink talkback uses the proprietary Baichuan media protocol over the
camera/NVR control/media connection. The GUI therefore does not pretend that
an RTSP write operation can send microphone audio.

This implementation delegates the Baichuan session to an external Reolink CLI
adapter. It captures mono PCM16 from the selected system microphone and writes
the raw bytes to the configured CLI stdin. The exact CLI command, sample rate,
and channel mapping must be verified against the installed CLI release and
the NVR's advertised talkback capability. Do not enable the control until the
CLI has been registered/configured and a physical test confirms audio at the
camera speaker. For a fully in-process implementation, replace
`Talkback` with a maintained Baichuan implementation that negotiates
`TalkAbility`, sends `TalkConfig` (message 201), streams encoded `Talk` frames
(message 202), and resets the session (message 11). This is a separate
protocol project and should be tested against the actual NVR firmware.

## Testing plan

1. Run `python -m compileall .` to catch syntax errors.
2. Confirm KeePassXC entry lookup works from a terminal.
3. Test NVR CGI login and `GetChannelstatus`; verify channel names/online flags.
4. Test each RTSP URL in VLC, first substream, then main stream.
5. Start app with one channel, then 2, then all online channels; watch CPU use.
6. Resize window and save; restart and confirm window/pane positions restore.
7. Test spotlight on one supported channel and verify mode/brightness remain
   unchanged after toggling.
8. Only after CLI configuration, test talkback with low speaker volume and
   verify start/stop behavior.
9. Test shutdown while streams are live; ensure all workers and subprocesses
   exit.

## Known issues to address in next iteration

- Use `ttk.Panedwindow` splitters for truly independent pane resizing.
- Add channel refresh/re-discovery without restarting the app.
- Add camera microphone audio playback / mute controls.
- Implement CLI capability checks and a version-specific talkback adapter.
- Improve shutdown: interrupt blocked RTSP reads and join all stream workers.
- Store spotlight state from API rather than only the GUI's last requested state.
- Add unit tests with mocked CGI responses and RTSP workers.
