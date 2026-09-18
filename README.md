# Neuro Atlas

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

For microphone access from a phone or Raspberry Pi over the LAN, use the
optional HTTPS server with Caddy and Waitress:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-https.txt
.venv/Scripts/python.exe -m main.https_server --host 192.168.1.213
```

Replace the example IP with the server's LAN address and install Caddy first.
Open `https://<server-ip>:8443`. Each client must trust the generated public root
certificate. See [HTTPS setup and device instructions](docs/https.md).
The launcher starts and stops both services, keeps the Python backend on loopback,
and stores private TLS state outside Git in `.local/https`. It does not change
system trust stores. The original HTTP development command remains available.

**Vollbild** hides both side panels and the mobile navigation, keeping the
conversation, microphone, playback and view state alive. Use the small **×**
button or Escape to return to the previous layout.

## Appearance

**Darstellung** in the existing panel switches between three styles:

- **Lernen** keeps the original region colors and lighting.
- **Natürlich** uses matte, muted rose/beige tissue with irregular tonal
  variation and soft lighting, without specular reflections. Closed cuts show
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
download, texture assets or WebGL postprocessing passes are needed. The source
geometry still limits how smooth and realistic the result can look.

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

Run the appearance browser check with local Chrome and Python Playwright:

```powershell
.venv/Scripts/python.exe -m tests.verify_appearance
```

It checks all three styles, state preservation, assistant focus, cuts, rotation,
saved preferences, blocked storage, full-detail geometry when available and the
mobile selector. It saves screenshots as `verification/appearance-*.png` and
makes no paid API calls.

Run mocked unit tests without API calls:

```powershell
.venv/Scripts/python.exe -m unittest tests.test_assistant -v
```

After installing the HTTPS dependencies and Caddy, run
`python -m unittest tests.test_https` and `python -m tests.verify_https`.
These verify the real TLS chain, proxy Origin checks, secure session cookies,
microphone upload, incremental text/audio delivery and the HTTP microphone hint.
The browser check uses simulated audio and mocked OpenAI; no billable requests
or system certificate installations are made.

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
