# Gehirn Viewer

## Setup

Create a virtual environment, install the runtime dependency, and start the app.

Windows PowerShell:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m main.brain_viewer
```

Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m main.brain_viewer
```

Then open http://localhost:5000. The 3D viewer requires WebGL and an internet
connection to load Three.js from jsDelivr.

## OpenAI assistant

Set `OPENAI_API_KEY` in the server environment before starting. Never put it in
JavaScript, the chat, or version-controlled files. The key is read only by Python;
no additional runtime package is needed.

```powershell
$env:OPENAI_API_KEY = "YOUR_API_KEY"
.venv/Scripts/python.exe -m main.brain_viewer
```

The turn-by-turn, non-Realtime assistant can select, show/hide, visually emphasize,
set axis cuts, and reset the view. A "markiere nur"/"zeige nur" request keeps the
target regions at 100% opacity and every other loaded region visible at 1%; the
camera remains fitted to the complete brain. It sends region IDs and the current
view state, not mesh geometry, to the Responses API. Actual browser execution
results are sent back before the model confirms a viewer action.

Text arrives incrementally over an NDJSON stream. Pressing **Escape** aborts the
browser request and asks the server to close its active OpenAI stream. Already
executed viewer actions remain in place. Requests already accepted by OpenAI may
still incur usage despite cancellation.

The default Responses request uses a balanced quality/latency profile:

- model `gpt-5.6-luna`
- `reasoning.effort="low"`
- `text.verbosity="medium"`
- `max_output_tokens=1600`
- `parallel_tool_calls=true`
- `tool_choice="auto"`
- `service_tier="default"`
- `stream=true` with `stream_options.include_obfuscation=false`
- `store=false`
- at most eight recent user/assistant messages retained locally

Web search is available automatically and displays clickable citations when used.
The assistant is instructed to search only for current/uncertain information or
explicit source requests, not stable anatomy basics. Search calls may add latency
and tool charges.

**Vorlesen** uses `gpt-4o-mini-tts`, `response_format="mp3"`,
`stream_format="audio"`, `speed=1.0`, detailed German delivery instructions, and the selected
**Marin** or **Cedar** voice; Marin is the default. Audio bytes are proxied and
played while they arrive when the browser supports Media Source Extensions.
Unchecking **Vorlesen**, changing voice, or sending another message cancels pending
playback. If autoplay is blocked, press Play in the audio player.
Restricted API keys need request access to `POST /v1/audio/speech`.

**Mikrofon starten** records locally until **Stoppen & senden** or the 60-second
limit. The recording is sent once to `gpt-4o-mini-transcribe` with `language="de"`
and `response_format="json"`; it is processed in memory and not written to disk.
Chrome/Edge microphone access requires `http://localhost:5000` or HTTPS. A plain
HTTP LAN address normally cannot access the microphone.

The three model IDs can be overridden with `OPENAI_MODEL`,
`OPENAI_TRANSCRIBE_MODEL`, and `OPENAI_TTS_MODEL`. Response quality can be tuned
with `OPENAI_REASONING_EFFORT`, `OPENAI_VERBOSITY`, and
`OPENAI_MAX_OUTPUT_TOKENS` (clamped to 256–8000). Conversation history expires
after one hour of inactivity. **Neues Gespräch** clears it immediately.

API references: [function calling](https://developers.openai.com/api/docs/guides/function-calling),
[streaming](https://developers.openai.com/api/docs/guides/streaming-responses), and
[web search](https://developers.openai.com/api/docs/guides/tools-web-search).

## Optimized meshes

The 43 `.obj` files in `export_preview` are optimized FreeSurfer triangle surfaces
(about 817,000 triangles total). The full-resolution source data is intentionally
not versioned. `manifest.json` records how the preview files were generated.

**Mesh-Details** switches between the optimized geometry (816,604 triangles,
20.2%) and the full local geometry (4,045,140 triangles); switching reloads the
viewer. **Bildauflösung** independently changes framebuffer pixels. Rendering
pauses after interactions and camera damping finish. **Schnittflächen schließen** uses
stencil passes only at planes intersecting visible regions; disable it for faster
open cuts. Caps share existing geometry buffers and do not create voxel data.

## Tests

Run mocked unit tests without API calls:

```powershell
.venv/Scripts/python.exe -m unittest tests.test_assistant -v
```

`verify_viewer`, `verify_highlight`, `verify_mobile`, `verify_non_realtime`, and
`verify_microphone` are non-billable browser checks requiring Chrome and Python
Playwright:

```powershell
.venv/Scripts/python.exe -m tests.verify_viewer
```

`tests.verify_assistant` is an optional live integration check. It requires a
configured API key and incurs usage. Screenshots are saved in the ignored
`verification` directory.

The server defaults to loopback with debug disabled. Add authentication and HTTPS
before binding this API-key-backed service to a public interface. On Jetson, create
a fresh Linux ARM virtual environment instead of copying the Windows `.venv`.
