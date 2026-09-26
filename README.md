# Neuro Atlas

## Setup

Create a virtual environment, install the runtime dependencies, and start the app.

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

Then open http://localhost:5000. The 3D viewer requires WebGL. Three.js 0.152.2 is bundled under
`static/vendor/three` (MIT license included), so rendering and gestures work
locally without an internet connection. Only the optional OpenAI assistant
requires internet access.

The supported display is Chromium on the same Raspberry Pi, connected to
`http://localhost:5000`. Flask and Waitress serve the local application;
there is no HTTPS proxy or certificate setup. Browser microphone access is
available on localhost.

**Vollbild** hides both side panels and the mobile navigation, keeping the
conversation, microphone, playback and view state alive. Press Escape to return to the previous layout; no exit button overlays the brain.

## Raspberry Pi 5: lokale Gestensteuerung

Flask, Kameraverarbeitung und Chromium laufen auf demselben Pi. MediaPipe läuft
auf der CPU; die IMX500 liefert das Kamerabild. Die Gesten verändern direkt die
Three.js-Kamera um das Gehirn herum. Es werden **keine Mausereignisse** erzeugt;
`evdev`, `/dev/uinput` und eine udev-Regel sind dafür nicht erforderlich.

Auf Raspberry Pi OS **64 Bit mit Desktop** im Projektordner:

```bash
sudo apt update
sudo apt install imx500-all python3-picamera2 python3-opencv python3-venv libportaudio2 chromium
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements-pi.txt
```

`--system-site-packages` ist für Picamera2 und libcamera aus den OS-Paketen nötig.
Nach erstmaliger Installation der Kamerafirmware neu starten. Bei einer bereits
vorhandenen virtuellen Umgebung deren Systempaket-Zugriff prüfen oder sie mit
`python3 -m venv --system-site-packages .venv` entsprechend aktualisieren.

Das Handmodell liegt im Projekt unter `models/hand_landmarker.task`.
Falls es bei einem neuen Checkout fehlt:

```bash
mkdir -p models
curl -fL https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task -o models/hand_landmarker.task
```

Start (ein Python-Prozess für Webserver und Kameraverarbeitung, **ohne sudo**):

```bash
.venv/bin/python -m main.brain_viewer --gestures
```

In einem zweiten Terminal Chromium im Kioskmodus starten:

```bash
chromium --kiosk http://localhost:5000
```

Kioskmodus öffnet die Webseite ohne Browserleisten im Vollbild. Der Knopf
**Vollbild** innerhalb der Webseite blendet zusätzlich die Bedienpanels aus.
Mit `Alt+F4` das Chromium-Fenster schließen.
`Strg+C` im Serverterminal beendet den Server und gibt die Kamera frei.
Ohne `--gestures` funktioniert der Viewer weiterhin mit Maus/Touch und benötigt
nur `requirements.txt`. Auch `python -m main.gesture_control` startet den
integrierten Viewer mit Gesten. Keinen zweiten Kameraprozess parallel starten.

**Desktop-Symbol:** Auf diesem Pi ist **Neuro Atlas** auf dem Desktop und im
Anwendungsmenü installiert. Es startet `start_neuro_atlas.sh`, lädt eine
vorhandene `.env` aus dem Projektordner und öffnet Chromium im Kioskmodus.
Die `.env` darf beispielsweise `export OPENAI_API_KEY="..."` enthalten.
Sie bleibt durch `.gitignore` ausgeschlossen.

Ein bereits auf Port 5000 laufender Viewer wird wiederverwendet. Andernfalls
startet das Symbol den Server mit `--gestures`. Ein selbst gestarteter Server
wird beim Schließen des Kioskfensters mit `Alt+F4` beendet; ein zuvor manuell
geöffneter Server läuft weiter. Mehrfaches Anklicken startet keine zweite Instanz.
Das Kioskfenster verwendet ein eigenes Chromium-Profil in `.local/chromium-kiosk`;
Mikrofonberechtigungen können dort beim ersten Mal erneut nötig sein.
Startfehler stehen in `.local/desktop.log`.

Die Vollbildansicht innerhalb der Webseite zeigt kein Kreuz mehr. **Escape**
blendet die Bedienpanels wieder ein, Chromium bleibt dabei im Kioskmodus.

**Bedienung:** Daumen (Landmark 4) und Zeigefinger (8) zusammenführen, dann die
Hand seitlich oder nach oben/unten bewegen. Finger öffnen oder Hand aus dem
Bild nehmen beendet das Drehen. Offene Hände verändern die Ansicht nicht.
Greifen pausiert **Langsam drehen**. Nach dem Loslassen (auch bei Handverlust)
bleibt die Ansicht 10 Sekunden stehen, danach startet die automatische Drehung
wieder. Erneutes Greifen bricht den Timer ab; erst nach dem nächsten Loslassen
beginnen erneut 10 Sekunden. Eine manuelle Änderung von **Langsam drehen**
hebt den laufenden Timer auf. Zoom, Fokus und anatomische Schnittachsen bleiben
erhalten. Die Wartezeit steht als `GESTURE_ROTATION_RESUME_MS = 10_000` in
`static/brain_viewer.js`.

Im Seitenpanel zeigt **Mit Handgesten drehen** den Zustand und erlaubt es, die
Gesten für diese Browseransicht zu pausieren. **Kameravorschau mit Handpunkten**
zeigt das gespiegelte Bild, die Nummern, die Verbindung 4–8 und den Zugpfeil.
Die Vorschau wird nur auf Anfrage aufbereitet; geschlossen spart sie CPU.

Parameter in `main/gesture_control.py`:

| Parameter | Standard | Wirkung |
| --- | --- | --- |
| `IDLE_FPS` | 3 | Auswertungen/s ohne aktive Hand |
| `IDLE_TIMEOUT_SECONDS` | 60 | Rückkehr zum Sparmodus nach letzter erkannter Hand |
| `ACTIVE_FPS` | 20 | Obergrenze im aktiven Modus; tatsächlich abhängig von CPU-Last |
| `PINCH_CLOSE` / `PINCH_OPEN` | 0.40 / 0.55 | Greifen/Loslassen relativ zur Handbreite 5–17 |
| `POINTER_SMOOTHING` | 0.4 | Glättung des Handpunkts; kleiner bedeutet ruhiger und träger |

Die Drehgeschwindigkeit steht als `ROTATION_SENSITIVITY` in
`static/gesture_control.js`. Serverparameter erfordern einen Neustart,
JavaScript-Änderungen ein Neuladen der Webseite.

Der Browser liest kleine Zustandsmeldungen vom lokalen Flask-Server (aktiv
höchstens 20/s, sparsam etwa 3/s). Kumulierte Bewegungen verhindern den Verlust
von Zwischenschritten. Nach Neuladen, Verbindungsabbruch oder einem versteckten
Tab wird eine neue Ausgangsposition verwendet, damit alte Bewegungen nicht
nachträglich abgespielt werden. Ohne Kamerabilder wird das Greifen freigegeben.
Mehrere sichtbare Browseransichten mit aktivierter Gestensteuerung empfangen
jeweils dieselben Handbewegungen.

Für weniger Grafiklast auf dem Pi: **Mesh-Details: Optimiert**,
**Bildauflösung: Sparsam** und **Langsam drehen** ausschalten, wenn das Modell
ruhig stehen soll. Die optionale Kameravorschau benötigt zusätzliche CPU-Zeit.

Der Betrieb erfolgt lokal auf dem Pi über `http://localhost:5000`, auch für
den Mikrofonzugriff. Kamera und deren Vorschau werden nicht an OpenAI gesendet.

Eine früher installierte `/etc/udev/rules.d/70-gesture-uinput.rules` wird vom
neuen Programm nicht verwendet. Sie kann entfernt werden, sofern kein anderes
Programm sie benötigt; diese Änderung entfernt keine Systemregeln automatisch.

## Appearance

**Darstellung** in the existing panel switches between three styles:

- **Lernen** keeps the original region colors and lighting.
- **Natürlich** uses matte, muted rose/beige tissue with irregular tonal
  variation and soft lighting, without specular reflections. Tonal variation is
  computed once per geometry and interpolated during rendering; per-pixel
  procedural noise and fine grain are removed. Closed cuts show
  cream-colored white matter and subtly differentiated gray matter/region tones;
  the legend follows the cut colors while cuts are active. The palette is an
  explanatory approximation, not measured tissue coloration. Gross-anatomy
  references: [Stony Brook University](https://renaissance.stonybrookmedicine.edu/pathology/neuropathology/chapter1).
- **Digital** is a translucent, self-lit cyan hologram with fine horizontal
  light lines and a soft halo. Deeper layers fade to keep the folds readable.
  Assistant focus colors selected regions amber; spoken mentions glow warm.

The browser remembers the choice, including across mesh-detail reloads. If
browser storage is blocked, switching still works for the current page.
Styles preserve camera, rotation, visibility, manual opacity, selection and cuts.
Automatic focus context uses 40% opacity in Digital and 3% in the other styles,
and follows style changes while preserving explicit opacity edits;
resetting the view keeps the selected style. Legend swatches and cut caps
follow the displayed surface colors.

Focus opacity is defined in `main/viewer_settings.py` and embedded in the page,
so the renderer and the assistant's acknowledgement checks use the same settings.
Restart the Python server after backend changes, then reload the browser. Reloading
only JavaScript can otherwise leave an older server validating new display values.

All styles reuse the same anatomical geometry and surface draw calls. Digital
transparency and its CSS halo add compositing work; the assistant's opacity
values multiply the hologram's own transparency. Its cut caps are also translucent.
The new styles lazily cache softened vertex normals for lighting, without moving
vertices or changing anatomical boundaries. The first switch can require a
brief preparation; subsequent switches reuse those normals. No extra mesh
download, texture assets or WebGL postprocessing passes are needed. Natural also caches one extra float per vertex for tissue variation (four bytes).
This adds a one-time CPU preparation and a small GPU buffer; the fragment shader
only blends two colors instead of recalculating three 3D noise samples per pixel.
Cut caps keep their tissue palette without a procedural grain shader. No new
texture, mesh triangles or draw calls are added. The source geometry still limits
how smooth and realistic the result can look.

## OpenAI assistant

Set `OPENAI_API_KEY` in the server environment before starting. Never put it in
JavaScript, the chat, or version-controlled files. The key is read only by Python;
no additional runtime package is needed.

```powershell
$env:OPENAI_API_KEY = "YOUR_API_KEY"
.venv/Scripts/python.exe -m main.brain_viewer
```

The turn-by-turn, non-Realtime assistant can show/hide, visually emphasize,
set axis cuts, and reset the view. Requests such as "zeige mir" or "markiere"
use `isolate_regions`: targets have 100% opacity and every other loaded brain
region remains visible at 40% in **Digital**, otherwise 3%, using the selected appearance (original region
colors in **Lernen**, rose in **Natürlich**, blue/amber in **Digital**). CSF stays hidden unless
explicitly requested as a target. A new focus
replaces the old one and clears old cuts while preserving camera perspective,
zoom, pan and the user's rotation choice. Explicitly requested cuts are applied afterwards.
Setting a cut (by assistant or slider) faces its exposed surface along the
anatomical X (sagittal), Y (coronal) or Z (axial/horizontal) axis and fits the complete cut face into view. These plane names also appear beside the sliders. Automatic
rotation pauses to keep that view steady; it can be re-enabled with **Langsam
drehen**. Removing the last cut resumes rotation if it was paused for the cut;
a manually disabled rotation stays off. This also applies to slider changes,
assistant commands, **Schnitte zurücksetzen**, and highlighting a new region.
Removing cuts leaves the camera in place. **Ansicht zurücksetzen**
still restores the default camera view.
The old `highlight_regions` name is no longer offered to the model;
nonempty legacy calls apply the same visible focus.

Technical action messages remain in the chat. The assistant is instructed to begin
directly with the anatomical explanation, without repeating successful actions,
context opacity or hidden CSF. Only unresolved tool errors need an explanation.

The API receives region IDs and the current view state, not mesh geometry.
Each browser action returns its own state snapshot. Focus success is checked
against target/context opacity, visibility, selection and cuts before the model
receives a successful tool result, so an unchanged view cannot confirm a new focus.

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
`stream_format="audio"`, `speed=1.1`, detailed German delivery instructions, and the selected
**Marin** or **Cedar** voice; Marin is the default. Audio plays while bytes arrive
when the browser supports Media Source Extensions, including answers with region
mentions. Other browsers download the audio before playing it.
Unchecking **Vorlesen**, changing voice, or sending another message cancels pending
playback. If autoplay is blocked, press Play in the audio player.
Restricted API keys need request access to `POST /v1/audio/speech` for playback
and `POST /v1/audio/transcriptions` for microphone input.

Mentioned regions receive a separate, softly pulsing two-second glow, including
regions outside the current selection. The overlay is visible through other
surfaces and respects cuts; selection, opacity, camera and visibility settings
are never changed. Hidden CSF remains excluded. Reduced-motion settings replace
pulsing with a steady glow. Names and left/right qualifiers are resolved against
the loaded meshes by `static/region_mentions.js`. The general names **Großhirn**
and **Kleinhirn** cue their respective cortex and white-matter meshes together;
specific cortex or white-matter names still cue only those meshes. It includes explicit German
case/plural forms, Latin and English names, umlaut/ASCII spellings, typographic
hyphens and common left/right qualifiers before or after the name. Additional
terminology was checked against [NLM MeSH](https://www.ncbi.nlm.nih.gov/mesh/68002421)
and [FIPAT's ventricular terminology](https://ifaa.unifr.ch/Public/TNAEntryPage/auto/part/LAEN/TAH8276%20P2%20EN.htm).
Longer specific names take priority, including when their mesh is unavailable;
they cannot fall back to a different structure via a shorter name. Unknown names,
unmeshed subregions and pronouns are not assigned speculative anatomy. This is
a curated name resolver, not a guarantee of understanding arbitrary paraphrases.

Normal answers use one continuous speech request, including all region names.
Only long answers are split, preferably at sentence boundaries, into at most
3,800 characters per request (below the [Speech API's 4,096-character limit](https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create)).
One following chunk is prefetched when needed. Glow never restarts the audio,
changes its playback speed, or adds a speech request.

`static/speech_timing.js` estimates mention positions from the answer's syllables
and punctuation, then scales them to the actual audio duration once the download
is complete. The growing stream buffer is never treated as the complete duration.
There is no Whisper analysis, extra API request, or analysis-related startup wait.
Cues follow the player's actual position; paused or blocked playback cannot
advance them, and forward seeks skip stale mentions. Repeated names each get a cue.

`DEFAULT_GLOW_OFFSET_SECONDS` in that file defaults to **0.3**: positive values
delay only the glow, negative values advance it, and **0** disables the offset.
This is an initial tuning value, not a measured correction. Timing remains an
estimate: a constant offset can reduce a consistent lead but cannot correct all
differences in emphasis or pauses. Playback and the two-second glow duration are
unchanged by the offset.
Without **Vorlesen**, mentions glow in text order at one-second intervals.
A new message, microphone recording, voice change, or Escape outside fullscreen
cancels pending cues. Natural playback completion lets the last glow expire.

**Mikrofon starten** records locally until **Stoppen & senden** or the 60-second
limit. The recording is sent once to `gpt-4o-mini-transcribe` with `language="de"`
and `response_format="json"`; it is processed in memory and not written to disk.
Chrome/Edge microphone access requires `http://localhost:5000` or HTTPS. A plain
HTTP LAN address normally cannot access the microphone.
The disabled microphone button now includes a visible explanation for insecure
connections or browsers without recording support.

The three model IDs can be overridden with `OPENAI_MODEL`,
`OPENAI_TRANSCRIBE_MODEL`, and `OPENAI_TTS_MODEL`. Response quality can be tuned
with `OPENAI_REASONING_EFFORT`, `OPENAI_VERBOSITY`, and
`OPENAI_MAX_OUTPUT_TOKENS` (clamped to 256–8000). Conversation history expires
after one hour of inactivity. **Neues Gespräch** clears it immediately.

API references: [function calling](https://developers.openai.com/api/docs/guides/function-calling),
[streaming](https://developers.openai.com/api/docs/guides/streaming-responses), and
[web search](https://developers.openai.com/api/docs/guides/tools-web-search).

## Optimized meshes

The viewer exposes 38 anatomical structures from the FreeSurfer triangle surfaces
in `export_preview`; 37 are visible by default because CSF is opt-in.
`main/mesh_catalog.py` excludes `lh.pial`, `rh.pial`, `lh.white`, `rh.white`, and
the duplicate `lh_hippo_mc` from the legend, mesh downloads and AI tools/context.
Their source files remain on disk. The anatomical `Cerebral-White-Matter` and
`Hippocampus` regions remain available. The full-resolution source data is
intentionally not versioned. `manifest.json` records how previews were generated;
displayed triangle counts include only the available structures.

**Mesh-Details** switches between the optimized geometry (576,008 triangles,
20.3%) and the full local geometry (2,842,152 triangles); switching reloads the
viewer. **Bildauflösung** independently changes framebuffer pixels. Rendering
pauses after interactions and camera damping finish. **Schnittflächen schließen** uses
stencil passes only at planes intersecting visible regions; disable it for faster
open cuts. Caps share existing geometry buffers and do not create voxel data.

## Tests

Run the appearance browser check with local Chromium and Python Playwright:

```bash
.venv/bin/python -m pip install playwright
.venv/bin/python -m tests.verify_appearance
```

It checks all three styles, state preservation, assistant focus, cuts, rotation,
saved preferences, blocked storage, full-detail geometry when available and the
mobile selector. It saves screenshots as `verification/appearance-*.png` and
makes no paid API calls.

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

`tests.verify_assistant_focus` reproduces the cortex-to-thalamus conversation
through the real browser and Flask API with mocked model calls. It checks the
visible change, 40% digital / 3% other context, repeated focus, hidden regions, old cuts, CSF opt-in
and the state returned to the model. It makes no billable API calls.

`tests.verify_narration` checks name resolution, two-second glow expiry,
unchanged persistent state, hidden CSF, multiple cues in a single uninterrupted
audio source/request, pause/seek timing, cancellation, and fullscreen continuity
with mocked OpenAI and locally generated silent audio.
`tests/region_mention_cases.json` holds additional positive and negative examples
for the name resolver, including inflections, sides and unavailable structures.

`tests.verify_camera` checks perspective preservation during focus, continued
rotation, resuming rotation after the last cut, manual rotation overrides,
both faces of X/Y/Z cuts, manual sliders, and complete cut-face framing
in wide and narrow viewports, without live API calls.

`tests.verify_assistant` is an optional live integration check. It requires a
configured API key and incurs usage. Screenshots are saved in the ignored
`verification` directory.

The server defaults to loopback with debug disabled. Add authentication and HTTPS
before binding this API-key-backed service to a public interface. On Jetson, create
a fresh Linux ARM virtual environment instead of copying the Windows `.venv`.

## Gestenprüfung

Auf dem Pi mit installierten `requirements-pi.txt`:

```bash
.venv/bin/python -m unittest tests.test_pinch_drag tests.test_gesture_service
```

Optionaler Browsertest mit dem systemweiten Chromium (keine OpenAI-Aufrufe):

```bash
.venv/bin/python -m pip install playwright
.venv/bin/python -m tests.verify_gestures
```

Dieser Test prüft lokale Mesh-Downloads, Greifen/Drehen/Loslassen,
Verbindungsabbrüche und unveränderten Zoom. Er schreibt Screenshots nach
`verification/`. Die Kamerahardware wird dabei durch Gestenzustände ersetzt.
