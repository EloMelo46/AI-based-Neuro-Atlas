from pathlib import Path
from flask import Flask, Response, abort, render_template_string, request, send_from_directory
import json
import os
import secrets

# Support both `python -m main.brain_viewer` and IDEs that execute this file
# directly. Direct execution otherwise places only `main/` on sys.path.
if __package__ in (None, ''):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from main.brain_assistant import create_assistant
    from main.mesh_catalog import available_mesh_names
    from main.viewer_settings import FOCUS_CONTEXT_OPACITIES
    from main.gesture_service import GestureService
else:
    from .brain_assistant import create_assistant
    from .mesh_catalog import available_mesh_names
    from .viewer_settings import FOCUS_CONTEXT_OPACITIES
    from .gesture_service import GestureService

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MESH_DIR = PROJECT_ROOT / "export_preview"
FULL_MESH_DIR = PROJECT_ROOT / "export_all_areas"
app = Flask(__name__, static_folder=str(PROJECT_ROOT / "static"), static_url_path="/static")
app.secret_key = os.environ.get('BRAIN_VIEWER_SESSION_SECRET') or secrets.token_hex(32)
app.config.update(MAX_CONTENT_LENGTH=11 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
app.register_blueprint(create_assistant(MESH_DIR))

gestures = GestureService()

HTML = r"""
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Neuro Atlas</title>
  <link rel="icon" type="image/svg+xml" sizes="any" href="{{ url_for('static', filename='favicon.svg') }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='assistant.css') }}">
  <style>
    body { margin: 0; overflow: hidden; background: #10141c; color: #fff; font-family: sans-serif; }
    canvas { display: block; }
    #info { position: absolute; top: 10px; left: 16px; z-index: 10; max-width: min(460px, 90vw); max-height: calc(100vh - 20px); overflow-y: auto; background: #10141ce6; padding: 0 12px 12px; border-radius: 8px; }
    #cuts { margin-top: 16px; }
    #cuts fieldset { border: 1px solid #526078; margin: 10px 0; border-radius: 6px; }
    #cuts label { display: grid; grid-template-columns: 65px minmax(80px, 1fr) 48px; gap: 8px; align-items: center; margin: 6px 0; }
    #cuts input { width: 100%; accent-color: #80baff; }
    #cuts output { text-align: right; font-variant-numeric: tabular-nums; }
    .hint { font-size: 13px; color: #b8c6d9; }
    #errors { color: #ffaaaa; max-height: 180px; overflow: auto; }
    #region-legend { margin-top: 16px; border: 1px solid #526078; border-radius: 6px; padding: 10px; }
    #region-legend summary { cursor: pointer; font-weight: bold; }
    .legend-actions { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0; }
    #region-list { list-style: none; padding: 0; margin: 0; max-height: 240px; overflow-y: auto; }
    .region-row { display: flex; align-items: center; gap: 8px; padding: 5px 2px; cursor: pointer; font-size: 13px; }
    .region-row input { accent-color: #80baff; flex-shrink: 0; }
    .region-color { width: 13px; height: 13px; border: 1px solid #ffffff66; border-radius: 3px; flex-shrink: 0; }
    .region-name { overflow-wrap: anywhere; }
    .region-state { color: #b8c6d9; font-size: 11px; margin-left: auto; }
    .region-row:has(input:not(:checked)) .region-name { opacity: 0.55; }
  </style>
  <link rel="stylesheet" href="{{ url_for('static', filename='viewer.css') }}">
  <script type="importmap">
    {"imports": {
      "three": "/static/vendor/three/build/three.module.js",
      "three/addons/": "/static/vendor/three/examples/jsm/"
    }}
  </script>
</head>
<body>
<header class="app-header"><div><span class="brand-icon" aria-hidden="true">◉</span> NEURO<span class="brand-light">ATLAS</span></div><div class="header-actions"><button id="fullscreen-toggle" type="button" aria-pressed="false" aria-label="Vollbild starten" title="Vollbild starten">Vollbild</button></div></header>
<p id="fullscreen-status" role="status" hidden></p>
<div id="scene" aria-label="Interaktives 3D-Gehirn"></div>
<div id="info">
  <h3>Gehirn – alle Regionen</h3>
  <p id="status" role="status">{{ count }} Regionen gefunden – 3D-Ansicht wird gestartet …</p>
  <button id="reset" disabled>Ansicht zurücksetzen</button>
  <section aria-label="Gestensteuerung">
    <label><input id="gesture-enabled" type="checkbox" checked> Mit Handgesten drehen</label>
    <p id="gesture-status" class="hint" role="status">Gestenerkennung wird geprüft …</p>
    <details id="gesture-preview">
      <summary>Kameravorschau mit Handpunkten</summary>
      <img id="gesture-image" alt="Kamerabild mit nummerierten Handpunkten und Greifanzeige" style="width:100%;max-width:640px">
    </details>
  </section>
  <p><label class="rotation-option"><input id="auto-rotate" type="checkbox" checked> Langsam drehen</label></p>
  <div class="viewer-settings">
    <div class="appearance-setting">
      <label for="appearance">Darstellung
        <select id="appearance">
          <option value="learning">Lernen</option>
          <option value="natural">Natürlich</option>
          <option value="digital">Digital</option>
        </select>
      </label>
    </div>
    <label for="mesh-detail">Mesh-Details
      <select id="mesh-detail">
        <option value="optimized"{% if mesh_detail == 'optimized' %} selected{% endif %}>Optimiert · {{ preview_triangles }} Dreiecke</option>
        <option value="full"{% if mesh_detail == 'full' %} selected{% endif %}{% if not full_mesh_available %} disabled{% endif %}>Voll · {{ full_triangles }} Dreiecke</option>
      </select>
    </label>
    <label for="resolution">Bildauflösung
      <select id="resolution"><option value="0.75">Sparsam</option><option value="1" selected>Standard</option><option value="native">Hoch (Displayauflösung)</option></select>
    </label>
  </div>
  <details id="region-legend" open>
    <summary>Legende · Areale ein-/ausblenden</summary>
    <div class="legend-actions">
      <button id="show-regions" disabled>Alle anzeigen</button>
      <button id="hide-regions" disabled>Alle ausblenden</button>
    </div>
    <p id="region-count" class="hint" role="status">Areal-Legende wird geladen …</p>
    <ul id="region-list">
      {% for name in meshes %}
      <li>
        <label class="region-row" for="region-{{ loop.index0 }}" title="{{ name }}">
          <input id="region-{{ loop.index0 }}" type="checkbox"{% if name != 'CSF.obj' %} checked{% endif %} disabled>
          <span id="region-color-{{ loop.index0 }}" class="region-color" aria-hidden="true"></span>
          <span class="region-name">{{ name[:-4] }}</span>
          <span id="region-state-{{ loop.index0 }}" class="region-state">Lädt …</span>
        </label>
      </li>
      {% endfor %}
    </ul>
  </details>
  <section id="cuts" aria-label="Schnittvolumen">
    <strong>Schnittvolumen</strong>
    {% for axis, plane, description in [('x', 'Sagittalebene', 'links ↔ rechts'), ('y', 'Koronalebene', 'hinten ↔ vorne'), ('z', 'Axialebene (horizontal)', 'unten ↔ oben')] %}
    <fieldset disabled id="cut-{{ axis }}">
      <legend>{{ axis|upper }} · {{ plane }}<span class="cut-direction">{{ description }}</span></legend>
      {% for bound, label, value in [('min', 'Von', 0), ('max', 'Bis', 100)] %}
      <label for="{{ axis }}-{{ bound }}">
        <span>{{ label }}</span>
        <input id="{{ axis }}-{{ bound }}" type="range" min="0" max="100" step="0.1" value="{{ value }}" aria-label="{{ plane }} ({{ axis|upper }}) {{ label }}">
        <output id="{{ axis }}-{{ bound }}-value" for="{{ axis }}-{{ bound }}">{{ value }} %</output>
      </label>
      {% endfor %}
    </fieldset>
    {% endfor %}
    <button id="reset-cuts" disabled>Schnitte zurücksetzen</button>
    <p><label><input id="fill-cuts" type="checkbox" checked> Schnittflächen schließen</label></p>
    <p class="hint">Gefüllte Schnitte benötigen zusätzliche Grafikleistung. Bei offenen Oberflächen sind Artefakte möglich.</p>
  </section>
  <ul id="errors" role="alert"></ul>
</div>
<details id="assistant-panel" open>
  <summary>Gehirn-Assistent</summary>
  <p id="assistant-status" role="status">Warte auf die 3D-Ansicht …</p>
  <div id="assistant-messages" role="log" aria-live="polite" aria-label="Gespräch"></div>
  <form id="assistant-form">
    <label for="assistant-input">Frage oder Anweisung</label>
    <textarea id="assistant-input" rows="3" maxlength="4000" placeholder="Zeige mir den linken Hippocampus und erkläre seine Funktion." required></textarea>
    <div class="assistant-settings">
      <label><input id="assistant-speak" type="checkbox" checked> Vorlesen</label>
      <label class="assistant-voice">Stimme <select id="assistant-voice"><option value="marin">Marin</option><option value="cedar">Cedar</option></select></label>
    </div>
    <div class="assistant-actions">
      <button id="assistant-send" disabled>Senden</button>
      <button id="assistant-mic" type="button" disabled aria-pressed="false" aria-describedby="assistant-mic-hint">Mikrofon starten</button>
      <button id="assistant-new" type="button">Neues Gespräch</button>
    </div>
    <p id="assistant-mic-hint" class="hint" role="status" hidden></p>
  </form>
  <p id="assistant-speech-status" class="hint" role="status" hidden>Sprachausgabe wird vorbereitet …</p>
  <audio id="assistant-audio" controls hidden aria-label="Gesprochene Antwort"></audio>
</details>
<nav class="mobile-nav" aria-label="Ansicht wählen">
  <button type="button" data-panel="scene" aria-pressed="true">3D-Ansicht</button>
  <button type="button" data-panel="regions" aria-controls="info" aria-pressed="false">Areale &amp; Schnitte</button>
  <button type="button" data-panel="assistant" aria-controls="assistant-panel" aria-pressed="false">Assistent</button>
</nav>
<script type="module" src="{{ url_for('static', filename='viewer_ui.js') }}"></script>
<script type="module" src="{{ url_for('static', filename='assistant_bridge.js') }}"></script>
<script id="mesh-list" type="application/json">{{ meshes|tojson }}</script>
<script id="focus-context-opacities" type="application/json">{{ focus_context_opacities|tojson }}</script>
<script>
  import({{ url_for('static', filename='brain_viewer.js')|tojson }}).catch((error) => {
    document.getElementById('status').textContent = '3D-Ansicht konnte nicht gestartet werden.';
    const item = document.createElement('li');
    item.textContent = 'Bitte lokale Dateien und WebGL prüfen: ' + error.message;
    document.getElementById('errors').appendChild(item);
    console.error(error);
  });
</script>
</body>
</html>
"""

@app.route("/")
def index():
    meshes = available_mesh_names(MESH_DIR)
    full_mesh_available = all((FULL_MESH_DIR / name).is_file() for name in meshes)
    mesh_detail = request.args.get('detail', 'optimized')
    if mesh_detail not in ('optimized', 'full') or (mesh_detail == 'full' and not full_mesh_available):
        mesh_detail = 'optimized'
    try:
        manifest = json.loads((MESH_DIR / 'manifest.json').read_text(encoding='utf-8'))
        manifest = [item for item in manifest if item['name'] in meshes]
        preview_count = sum(int(item['preview']) for item in manifest)
        full_count = sum(int(item['original']) for item in manifest)
    except (OSError, ValueError, KeyError, TypeError):
        preview_count = full_count = 0
    triangle_label = lambda count: f'{count:,}'.replace(',', chr(0x2019)) if count else '–'
    return render_template_string(
        HTML, meshes=meshes, count=len(meshes), mesh_detail=mesh_detail,
        full_mesh_available=full_mesh_available, focus_context_opacities=FOCUS_CONTEXT_OPACITIES,
        preview_triangles=triangle_label(preview_count), full_triangles=triangle_label(full_count))

@app.route("/mesh/<path:filename>")
def mesh(filename):
    if filename not in available_mesh_names(MESH_DIR):
        abort(404)
    detail = request.args.get('detail', 'optimized')
    if detail not in ('optimized', 'full'):
        abort(400)
    directory = FULL_MESH_DIR if detail == 'full' else MESH_DIR
    if detail == 'full' and not (directory / filename).is_file():
        abort(404)
    return send_from_directory(directory, filename)

@app.get('/api/gestures/state')
def gesture_state():
    response = app.json.response(gestures.snapshot())
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/gestures/preview')
def gesture_preview():
    image = gestures.preview()
    return Response(image or b'', status=200 if image else 204,
                    mimetype='image/jpeg', headers={'Cache-Control': 'no-store'})


def main(argv=None):
    import argparse
    from waitress import serve
    parser = argparse.ArgumentParser(description='Lokaler Neuro Atlas auf dem Raspberry Pi')
    parser.add_argument('--gestures', action='store_true', default=os.environ.get('NEURO_GESTURES') == '1')
    parser.add_argument('--host', default=os.environ.get('BRAIN_VIEWER_HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=5000)
    args = parser.parse_args(argv)
    if args.gestures:
        gestures.start()
    print(f'Neuro Atlas: http://{args.host}:{args.port}', flush=True)
    try:
        serve(app, host=args.host, port=args.port, threads=8)
    finally:
        gestures.stop()


if __name__ == '__main__':
    main()
