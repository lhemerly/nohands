# NoHands

NoHands adds local, audio-first control and spoken feedback to Codex CLI on Linux. It targets COSMIC on Wayland and is designed to keep working while a game owns the screen through Gamescope.

## How it works

- **Speech recognition:** Moonshine Streaming Small by default, running locally on CPU. Use `tiny_streaming` to reduce load or `medium_streaming` for higher accuracy.
- **Speech output:** Kokoro, through Moonshine Voice's local TTS integration.
- **Meaning:** common service controls such as stop, status and repeat are routed locally. Everything else is sent with its literal transcript to Codex, which interprets the request and repository context.
- **Codex:** `codex exec --json` produces structured events. NoHands stores the returned thread ID per workspace and uses `codex exec resume` for follow-up turns.
- **Audio activation:** a toggle command can be bound to a COSMIC shortcut or controller macro. No overlay is required.
- **Storage:** local SQLite under `$XDG_STATE_HOME/nohands` (normally `~/.local/state/nohands`).

The ASR and TTS are local. Codex continues to use the account and provider configured by your Codex CLI installation.

## Requirements

- Linux with PipeWire audio (CachyOS/COSMIC tested as the target environment; audio device testing still needs to be done on the target desktop).
- Python 3.11 or newer.
- Codex CLI installed and signed in (`codex login`).
- A working microphone and audio output.

## Install

```bash
git clone https://github.com/lhemerly/nohands.git
cd nohands
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
nohands init
```

The first daemon start downloads Moonshine and Kokoro model assets into the runtime's model cache. Later starts work offline. The models run locally; the Codex request itself uses your configured Codex account.

Check dependencies and start the service:

```bash
nohands doctor
nohands daemon --cwd "$HOME/src/my-project"
```

While it is running, test from another terminal:

```bash
nohands toggle   # start/stop microphone capture; speak between presses
nohands status
nohands stop     # cancel the current Codex process
nohands repeat
nohands quiet
```

When you toggle capture off, the final transcript is sent to Codex. Codex's answer is stored locally and spoken through Kokoro. Each workspace retains its own Codex thread.

### COSMIC shortcut

Create a custom COSMIC shortcut that runs:

```bash
/home/YOU/src/nohands/.venv/bin/nohands toggle
```

Bind it to a key or controller macro you do not use in the game. The hotkey invokes a local Unix socket command, so the capture service remains independent of the focused application. The socket is placed in `$XDG_RUNTIME_DIR` with mode `0600`.

For a controller that emits keyboard events, use the controller's own mapping utility to map a button/chord to that command. A future native evdev backend can remove that external mapping step; this first release uses COSMIC's command shortcut as its portable activation path.

### Start the service on login

Create `~/.config/systemd/user/nohands.service` and replace the workspace path:

```ini
[Unit]
Description=NoHands local audio service for Codex
After=pipewire.service wireplumber.service

[Service]
Type=simple
ExecStart=%h/src/nohands/.venv/bin/nohands daemon --cwd %h/src/my-project
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

Then enable it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now nohands.service
```

Run one request without microphone or TTS to verify the Codex adapter:

```bash
nohands run "Summarize this repository" --cwd "$HOME/src/my-project"
```

## Controls

Say one of these while capture is active, then toggle capture off:

- **“Stop” / “Cancel this run”** — terminate the active Codex process.
- **“Status” / “What is happening?”** — hear the latest service state.
- **“Repeat that”** — hear the last Codex response again.
- **“Be quiet”** — stop current speech playback.
- Any other speech is sent to Codex as a development request.

The literal transcript is persisted with the response. NoHands asks Codex to keep its final response short enough to listen to and include verification results.

## Configuration

`~/.config/nohands/config.toml`:

```toml
[voice]
language = "en"
model = "small_streaming" # tiny_streaming | small_streaming | medium_streaming
tts_voice = "kokoro_af_heart"

[audio]
speech_enabled = true

[codex]
command = "codex"
workspace = "/home/YOU/src/my-project"
```

## Development

```bash
python -m pip install -e '.[dev]'
pytest
```

The integration tests exercise local command routing, Codex JSONL parsing, transcript summaries and SQLite persistence without loading models or making Codex requests. Hardware microphone/playback verification must be run on the target machine with `nohands doctor` and the real audio device.

## Current limits

- The activation control is a press-to-toggle recording session, not a key-hold PTT gesture. It is friendlier to COSMIC custom shortcuts and controller mappings that launch commands.
- NoHands speaks concise Codex status and final messages; it does not read command output or code aloud.
- Codex approval prompts are governed by the user's existing Codex CLI configuration. NoHands does not enable full-auto or bypass approvals.
- The current transport launches `codex exec` for each turn and resumes the saved thread. The voice and thread interfaces are isolated so a later app-server adapter can provide richer live events and approval controls.

## License

MIT. See [LICENSE](LICENSE).
