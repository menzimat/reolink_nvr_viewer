# Reolink NVR Viewer (Tkinter)

A Linux/Python desktop viewer for Reolink NVR channels. It discovers the NVR
channel inventory through Reolink CGI, receives video over RTSP, allows any
subset of channels to be displayed, and persists the window/pane layout.

## Important scope and compatibility notes

- The RTSP path follows Reolink's documented NVR form:
  `rtsp://user:password@NVR:554/Preview_01_sub` (channel is 1-based and
  zero-padded). The app builds the URL internally and URL-escapes credentials.
- CGI channel indexes are zero-based. The code converts index 0 to RTSP channel
  01 and uses the zero-based index for CGI commands.
- Spotlight control uses `GetWhiteLed` followed by `SetWhiteLed`, preserving
  the current mode, brightness, schedule, and AI-detection configuration while
  changing only `state`.
- Two-way audio is **not carried by RTSP**. Reolink talkback uses the
  proprietary Baichuan media protocol. This app has a push-to-talk adapter that
  captures microphone PCM and pipes it to the Reolink CLI. The adapter is
  deliberately disabled by default: install/configure a compatible
  `reolink-cli`, verify the command syntax for your installed version, then set
  `audio.enabled: true` and edit `audio.command` in YAML. Do not assume that
  every camera supports a speaker/talkback; verify the camera's feature set.
- This application is an initial implementation and has not been tested
  against the user's physical NVR. Test spotlight and talkback on one channel
  before relying on them.

## Installation (Linux Mint)

Use a virtual environment. Python 3.11+ is recommended.

```bash
sudo apt update
sudo apt install -y python3-tk python3-venv ffmpeg libgl1 libglib2.0-0 \
    portaudio19-dev keepassxc

mkdir -p ~/Projects/reolink-nvr-viewer
cd ~/Projects/reolink-nvr-viewer
# Extract this project here.
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp config.yaml.example config.yaml
chmod 600 config.yaml
```

Edit `config.yaml`:
- `nvr.host`: NVR LAN address.
- `nvr.http_port`: use 443 for HTTPS or 80 for HTTP, matching the NVR.
- `nvr.https`: true/false to match the chosen port.
- `nvr.rtsp_port`: normally 554.
- `nvr.username`: NVR account name.
- `nvr.keepass_database`: absolute path to the KeePassXC `.kdbx`.
- `nvr.keepass_entry`: exact KeePassXC entry title containing the NVR password.
- `nvr.keepass_group`: optional KeePassXC group path.
- `video.stream`: `sub` is recommended for multiple panes; use `main` for quality.
- `gui.excluded_channels`: optional list of 1-based NVR channel numbers to
  omit from the channel menu and RTSP loading.
- `gui.channels`: optional per-channel `streams` list, keyed by 1-based NVR
  channel number. For example, `"9": {streams: [main, sub]}` opens both RTSP
  streams as separate panes. Channels without an entry use `video.stream`.
- `gui.dark_mode`: set to `true` to use the dark application color scheme.

The NVR password is not stored in YAML. On launch, `keepassxc-cli` retrieves
the password from the named KeePassXC entry. The KeePassXC CLI may prompt for
the database master password in the terminal. Do not run the application in a
context without an interactive terminal until you have arranged a secure
KeePassXC unlock method.

Run:

```bash
source .venv/bin/activate
python main.py
```

## NVR setup checklist

1. Assign the NVR a stable LAN IP (DHCP reservation recommended).
2. Enable RTSP and HTTP(S)/CGI access in NVR network/port settings.
3. Confirm the configured RTSP URL works in VLC before debugging this app.
4. Use a dedicated NVR account with only the permissions required, if the
   firmware supports the required per-user permissions.
5. Confirm each camera supports a speaker and two-way audio before enabling
   talkback.
6. Do not forward RTSP/HTTP/9000 ports to the public Internet. Use LAN or VPN.

## GUI behavior

- `Channels` menu: show all, show online, or toggle individual channels.
- `Layout` menu: choose 1–4 columns or save immediately.
- Each camera pane has a Spotlight button that shows its confirmed ON/OFF state;
  the button is yellow when ON.
- If audio is enabled, hold `Hold to Talk` while speaking; release to stop.
- Drag the splitters between panes to resize them horizontally and vertically.
  Pane dimensions, row/column ordering, visible channels, and main-window geometry are saved to
  `~/.config/reolink-nvr-viewer/layout.json`. Each channel/stream pane is saved
  independently, so additional stream panes restore with their own geometry.

## Known limitations / next refinements

- The pane layout uses nested `ttk.Panedwindow` splitters. The current layout
  is row/column based; arbitrary tile spanning and drag-reordering are not
  implemented.
- The talkback subprocess command is intentionally configurable. CLI command
  line options and channel-selection syntax may vary between CLI versions.
  Validate with `reolink-cli --help` and the audio-talk documentation before
  enabling. The application does not silently claim talkback is working.
- Audio playback from camera microphones is not yet implemented; this release
  focuses on video display and outbound push-to-talk.
- `open_timeout_seconds` is retained in configuration for future FFmpeg
  timeout tuning; OpenCV backend timeout behavior varies by build.
- The current GUI polls frames at 10 Hz. Increase/decrease this in
  `ViewerApp._refresh` if needed.
- HTTP certificate verification is configurable. For self-signed NVR
  certificates `verify_tls: false` may be necessary on a trusted LAN. Prefer a
  trusted certificate where practical.
