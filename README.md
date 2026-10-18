# Neuro Atlas

An interactive 3D brain atlas based on my personal MRI scan, designed for the
Raspberry Pi 5. Brain regions can be explored, sliced, and selected using a mouse,
hand gestures, or an AI assistant.

## How the project came about

For this project, I segmented my personal MRI scan using FreeSurfer. I then
created 3D models of the individual brain regions and exported them as GLB files.
To help the Raspberry Pi render them more smoothly, I simplified and compressed
the meshes using tools from the Meshoptimizer ecosystem, including `gltfpack`:
fewer triangles reduce GPU load, while quantization and Meshopt compression
reduce file sizes.

Building on this, I developed the interactive atlas with gesture control and
AI assistance. A local Python server using Flask/Waitress serves the prepared
models, while Three.js handles rendering in the browser.

## Features and controls

- **3D view:** Rotate and zoom the brain, select regions or groups, and adjust
  visibility and opacity.
- **Slices:** Sagittal, coronal, and axial slices; validated models support
  filled cross-sections.
- **Appearance:** Learning view, natural tissue rendering, digital hologram or original MRT scan.
  **Fullscreen** hides the control panels; **Escape** brings them back.
- **AI assistant:** Ask anatomical questions by text or microphone and control
  the view, for example, “Show and explain the hippocampus.” Answers can be read
  aloud, and mentioned regions light up.
- **Hand gestures:** Pinch your thumb and index finger together and move your
  hand to rotate the brain. Holding only your index finger up for at least
  0.6 seconds starts voice recording; lowering it stops and sends the recording.

Region groups and their scientific limitations are documented in
[docs/region-groups.md](docs/region-groups.md). Functional assignments are
anatomical approximations, not individually measured functional maps.

## Your own model data

Personal MRI data, models, and measurement reports remain local and are excluded
through `.gitignore`. A compatible export is required for your own installation:

```text
segmentation_export/
├── models/                   # GLB files for the regions
├── regions_manifest.tsv      # Region IDs, model paths, and metadata
├── region_volumes.json       # Segmentation volumes for the assistant
└── geometry_validation.json  # Validation results for these exact GLBs
```

Alternatively, set `NEURO_ATLAS_EXPORT_DIR` to the export directory.
The manifest must match the format in [main/mesh_catalog.py](main/mesh_catalog.py);
arbitrary GLB files alone are not sufficient. Without volume data, the assistant
has no volume information. Without a matching positive geometry report,
cross-sections remain unfilled.

## Installation on the Raspberry Pi 5

Requirements: Raspberry Pi OS **64-bit with desktop**, Python **3.11 or later**,
and Chromium with WebGL. The gesture control used here also requires a camera,
Picamera2, and MediaPipe for hand landmarks detection.

From the project directory:

```bash
sudo apt update
sudo apt install python3-venv chromium curl libportaudio2
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements.txt
```

For hand gestures, also run:

```bash
sudo apt install imx500-all python3-picamera2 python3-opencv
mkdir -p models
curl -fL https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task -o models/hand_landmarker.task
```

Reboot after installing the camera firmware for the first time.
`--system-site-packages` provides access to the camera packages installed by the OS.
`models/hand_landmarker.task` is the hand detection model from the MediaPipe library.

## Running the app and configuring AI

After providing the model data:

```bash
.venv/bin/python -m main.brain_viewer
# To enable camera gestures, use this instead:
# .venv/bin/python -m main.brain_viewer --gestures
```

Open **http://localhost:5000** in Chromium and allow microphone access if needed.
`Ctrl+C` stops the server. Once set up, the viewer and gestures work offline.

For the optional OpenAI assistant, set the following before starting the server:

```bash
export OPENAI_API_KEY="YOUR_API_KEY"
```

The AI features require internet access and incur API costs. Depending on the
feature, text, recorded speech, and region context, including available volume
measurements, are sent to OpenAI; brain models and camera images remain local.
The application is intended to run locally on `localhost`.

**Desktop/kiosk:** `bash start_neuro_atlas.sh` loads a local `.env` file and starts
the server with gestures and Chromium in kiosk mode; an existing server is reused.
Starting Python directly does not automatically load `.env`.
For a desktop shortcut, rename `neuro-atlas.desktop.example` to
`neuro-atlas.desktop`, replace `/ABSOLUTER/PROJEKTPFAD`, and install the file
as a desktop shortcut. `Alt+F4` closes the kiosk window; startup errors are
logged in `.local/desktop.log`.