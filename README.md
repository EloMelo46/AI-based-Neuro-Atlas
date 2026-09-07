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
JavaScript, the chat, or version-controlled files. Optional `OPENAI_MODEL` defaults
to `gpt-4.1-mini`. The key is read only by Python; no new runtime package is needed.

Example PowerShell startup (replace the placeholder locally):

```powershell
$env:OPENAI_API_KEY = "YOUR_API_KEY"
.venv/Scripts/python.exe -m main.brain_viewer
```

The chat can highlight, show/hide, isolate, focus, set axis cuts, and reset the view.
It sends region IDs and current view state, not mesh geometry, to the Responses API.
Web search is optional and displays clickable citations. **Vorlesen** uses
OpenAI `gpt-4o-mini-tts` speech synthesis and is enabled by default. Choose **Marin**
or **Cedar**; Marin is the default. The API key additionally needs **Text-to-speech
(`/v1/audio/speech`) → Request**. Speech generation incurs API usage. The interface
labels the voice as AI-generated. Starting a microphone recording, sending another
message, changing voice or pressing **Sprachausgabe stoppen** cancels playback and
pending browser requests. Cancellation does not guarantee cancellation of billing
for a request already received by OpenAI. If autoplay is blocked, press Play in the
audio player. Browser/Windows speech synthesis is no longer used.

**Mikrofon starten** records your voice; **Stoppen & senden** transcribes it with
OpenAI and automatically submits the recognized text to the assistant. Recording
stops after 60 seconds; the microphone is released after stopping or on page exit.
Audio is processed in memory and is not written to a local file. OpenAI audio
processing incurs API usage. Set `OPENAI_TRANSCRIBE_MODEL` to override the default
`gpt-4o-mini-transcribe`. Restricted keys additionally need request access to
`POST /v1/audio/transcriptions`. Allow microphone access in Chrome/Edge and open
the viewer on `http://localhost:5000` or HTTPS; plain HTTP over a LAN IP cannot
normally access a microphone. This is turn-by-turn voice input, not continuous
listening. `tests/verify_microphone.py` tests capture/upload and automatic chat submission
using a fake browser microphone and mocked OpenAI responses, without recording you.
Chat requests and web searches incur OpenAI API usage.

Tool arguments are checked on the server; only predefined operations run in the
browser. Actual execution results are sent back before the model confirms success.
Conversation history is held in server memory, limited to eight recent exchanges,
and expires after an hour of inactivity. **Neues Gespräch** clears it. API requests
use `store=false`; this does not override OpenAI's applicable data retention policy.

The server defaults to loopback with debug disabled. `BRAIN_VIEWER_HOST` can change
the bind address, but authentication and HTTPS must be added before exposing this
API-key-backed service to other users or public networks. For Jetson, recreate the
Python environment on Linux ARM; do not copy the Windows `.venv`.

Tests: `.venv/Scripts/python.exe -m unittest tests.test_assistant -v` uses mocked API
responses. `tests/verify_assistant.py` uses Chrome/Playwright and makes real, billable
OpenAI calls. It verifies the complete chat-to-viewer round trip.

API references: [function calling](https://developers.openai.com/api/docs/guides/function-calling)
and [web search](https://developers.openai.com/api/docs/guides/tools-web-search).

The 43 `.obj` files in `export_preview` are optimized binary FreeSurfer triangle
surfaces. The viewer also accepts ordinary Wavefront OBJ files. `manifest.json`
records how the bundled preview files were generated.

## Optimized meshes

`export_preview` contains the precomputed surfaces served by Flask (about 817,000
triangles in total). The full-resolution source data is intentionally not versioned.
**Bildauflösung** changes framebuffer pixels, not mesh detail.
`manifest.json` preserves the generation metadata for these display meshes.

Rendering pauses after interactions and camera damping finish. Resolution defaults
to one framebuffer pixel per CSS pixel; choose **Sparsam** for 0.75 or **Hoch** for
the display's native device pixel ratio, without a fixed 2x cap.
Legend checkboxes hide regions without reloading geometry.

**Schnittflächen schließen** uses stencil passes only at planes intersecting visible
regions. Disable it for faster open cuts. Caps share existing geometry buffers and
do not create voxel data. On overlapping exports, smaller regions receive drawing
priority on the cut plane; this is a display convention, not a segmentation merge.

## Tests

The test suite lives in `tests`. Run the unit tests without API calls with:

```powershell
.venv/Scripts/python.exe -m unittest tests.test_assistant -v
```

The `verify_viewer`, `verify_highlight`, `verify_mobile`, `verify_microphone`, and
`verify_realtime_errors` modules are browser checks that do not make billable OpenAI
requests. They require Chrome and Python Playwright. For example:

```powershell
.venv/Scripts/python.exe -m tests.verify_viewer
```

`tests.verify_assistant` and `tests.verify_realtime` are optional live integration
checks. They require a configured OpenAI API key and incur API usage. Generated
screenshots are saved in the ignored `verification` directory.
# Realtime-Sprachgespräch

Nach einem Serverneustart und Strg+F5 im Browser **Realtime starten** anklicken und das Mikrofon erlauben. Danach frei sprechen; semantische Sprecherkennung mit niedriger Reaktionsbereitschaft wartet auf das inhaltliche Ende der Äußerung. Erneutes Sprechen kann die Antwort unterbrechen. **Realtime stoppen** beendet die Verbindung und gibt das Mikrofon frei. Währenddessen sind Textchat und Einzelaufnahme gesperrt.

Die Audioverbindung läuft über WebRTC direkt zu OpenAI. Der Python-Server erstellt einen kurzlebigen Sitzungsschlüssel; der normale API-Key bleibt auf dem Server. Benötigt wird Realtime-Zugriff am API-Key (Realtime `/v1/realtime`: Request), für Webrecherche zusätzlich Responses-Zugriff. Standardmodell ist `gpt-realtime-2.1-mini`, überschreibbar mit `OPENAI_REALTIME_MODEL`. Marin/Cedar und Websuche vor dem Start auswählen. Die Vorlesen-Option betrifft den Textchat.

Jeder Start erzeugt ein neues Sprachgespräch mit dem aktuellen Viewerzustand, ohne den bisherigen Textchat zu übernehmen. Realtime-Antworten verwenden niedrigen Reasoning-Aufwand und sind auf 4.000 Ausgabetokens sowie normalerweise drei kurze Sätze begrenzt; die Konversation behält höchstens 8.000 Tokens nach den Anweisungen. Die Realtime-Werkzeuge enthalten die vollständigen erlaubten Areal-IDs, und kombinierte Vieweränderungen sollen vollständig abgearbeitet werden. Das Setzen einer Deckkraft blendet die betroffenen Areale automatisch ein, auch wenn sie zuvor isoliert oder deaktiviert waren. Markieren, Sichtbarkeit, Kamera und Schnitte nutzen die bestehende serverseitige Aktionsvalidierung. Webrecherche erfolgt über den Server; Quellen erscheinen im Chat. Audio wird während der Verbindung laufend übertragen, und es fallen OpenAI-API-Kosten an. Bei einem kurzfristigen Rate-Limit zeigt die App OpenAIs Fehlerdetail und Limitwerte an und versucht die letzte Antwort nach dem gemeldeten Reset einmal erneut. Für den Browser sind localhost oder HTTPS sowie WebRTC erforderlich.

Tests: `python -m unittest tests.test_assistant` ohne API-Aufrufe; `python -m tests.verify_realtime` prüft eine echte WebRTC-Verbindung, Sprachausgabe, eine Vieweraktion und Aufräumen beim Stoppen (API-Nutzung, synthetisches Mikrofon, Chrome und Playwright erforderlich).
