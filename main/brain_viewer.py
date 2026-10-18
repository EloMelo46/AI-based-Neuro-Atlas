from pathlib import Path
from flask import Flask, Response, abort, render_template_string, request, send_from_directory
import os
import secrets

# Support both `python -m main.brain_viewer` and IDEs that execute this file
# directly. Direct execution otherwise places only `main/` on sys.path.
if __package__ in (None, ''):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from main.brain_assistant import create_assistant
    from main.mesh_catalog import DEFAULT_EXPORT_DIR, available_mesh_names, load_regions, region_groups, selection_aliases
    from main.geometry_validation import cut_validation
    from main.viewer_settings import FOCUS_CONTEXT_OPACITIES
    from main.gesture_service import GestureService
    from main.mri_viewer import create_mri_blueprint, MRIStore, mri_regions
else:
    from .brain_assistant import create_assistant
    from .mesh_catalog import DEFAULT_EXPORT_DIR, available_mesh_names, load_regions, region_groups, selection_aliases
    from .geometry_validation import cut_validation
    from .viewer_settings import FOCUS_CONTEXT_OPACITIES
    from .gesture_service import GestureService
    from .mri_viewer import create_mri_blueprint, MRIStore, mri_regions

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MESH_DIR = DEFAULT_EXPORT_DIR
app = Flask(__name__, static_folder=str(PROJECT_ROOT / "static"), static_url_path="/static")
app.secret_key = os.environ.get('BRAIN_VIEWER_SESSION_SECRET') or secrets.token_hex(32)
app.config.update(MAX_CONTENT_LENGTH=11 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
mri_store = MRIStore(os.environ.get('NEURO_ATLAS_MRI_DIR', str(PROJECT_ROOT / 'original_mri')),
                     MESH_DIR, PROJECT_ROOT / '.local' / 'mri')
app.register_blueprint(create_assistant(MESH_DIR, mri_store.catalog))
app.register_blueprint(create_mri_blueprint(PROJECT_ROOT, MESH_DIR, mri_store))

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
  <link rel="stylesheet" href="{{ url_for('static', filename='mri_viewer.css') }}">
  <script type="importmap">
    {"imports": {
      "three": "/static/vendor/three/build/three.module.js",
      "three/addons/": "/static/vendor/three/examples/jsm/"
    }}
  </script>
</head>
<body data-initial-viewer="{{ initial_viewer }}" data-viewer="{{ initial_viewer }}">
<header class="app-header"><div><span class="brand-icon" aria-hidden="true">◉</span> NEURO<span class="brand-light">ATLAS</span></div><div class="header-actions"><button id="fullscreen-toggle" type="button" aria-pressed="false" aria-label="Vollbild starten" title="Vollbild starten">Vollbild</button></div></header>
<p id="fullscreen-status" role="status" hidden></p>
<div id="scene" aria-label="Interaktives 3D-Gehirn"></div>
<section id="mri-scene" aria-label="MRT-Ansicht" hidden>
  <div class="mri-toolbar">
    <label>Aufnahme <select id="mri-scan"><option value="brain">Brain Only</option></select></label>
    <label><input id="mri-overlay" type="checkbox" checked> Regionen markieren</label>
    <button id="mri-clear-selection" type="button" disabled>Markierung entfernen</button>
    <button id="mri-reset" type="button">MRT zurücksetzen</button>
  </div>
  <p id="mri-status" role="status">MRT wird vorbereitet …</p>
  <div id="mri-viewers">
    <article class="mri-window" id="mri-main-window">
      <header><strong id="mri-scan-title">MRT</strong><span>Koronal · Sagittal · Axial · 3D</span></header>
      <div class="mri-canvas-host"><canvas id="mri-main" aria-label="MRT: drei Schnitte und drehbare 3D-Ansicht" tabindex="0"></canvas></div>
    </article>
  </div>
  <p class="mri-help">Schnitte: klicken und scrollen · 3D: greifen und ziehen · Rechts ziehen: Kontrast · Handzeiger: ansteuern und zugreifen</p>
</section>
<div id="gesture-pointer" aria-hidden="true" hidden></div>
<aside id="voice-feedback" aria-label="Spracheingabe" hidden>
  <span class="voice-indicator" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>
  <div><strong id="voice-feedback-title" role="status" aria-live="polite"></strong><small id="voice-feedback-hint"></small></div>
  <button id="voice-feedback-stop" type="button">Stoppen &amp; senden</button>
</aside>
<div id="info">
  <h3>{{ 'MRT · Originalaufnahmen' if initial_viewer == 'mri' else 'Gehirn – alle Regionen' }}</h3>
  <p id="status" role="status">{% if initial_viewer == 'mri' %}MRT-Ansicht wird gestartet …{% else %}{{ count }} Regionen gefunden – 3D-Ansicht wird gestartet …{% endif %}</p>
  <button id="reset" disabled>Ansicht zurücksetzen</button>
  <section aria-label="Gestensteuerung">
    <label><input id="gesture-enabled" type="checkbox" checked> Handgesten aktiv</label>
    <p id="gesture-status" class="hint" role="status">Gestenerkennung wird geprüft …</p>
    <details id="gesture-preview">
      <summary>Kameravorschau mit Handpunkten</summary>
      <img id="gesture-image" alt="Kamerabild mit nummerierten Handpunkten und Gestenanzeige" style="width:100%;max-width:640px">
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
          <option value="mri">MRT</option>
        </select>
      </label>
    </div>
    <label for="mesh-detail">Mesh-Details
      <select id="mesh-detail" disabled title="Vorbereitete Meshopt-GLBs">
        <option value="optimized"{% if mesh_detail == 'optimized' %} selected{% endif %}>Optimiert · {{ preview_triangles }} Dreiecke</option>
        <option value="full" disabled>Voll · nicht exportiert</option>
      </select>
    </label>
  </div>
  <section id="mri-region-controls" hidden>
    <label for="mri-region">Region oder Gruppe im MRT markieren</label>
    <select id="mri-region"><option value="">Bitte wählen …</option></select>
    <button id="mri-show-region" type="button">Region zeigen</button>
    <p class="hint">Auch per Sprache: «Zeige mir den Hirnstamm.»</p>
  </section>
  <details id="region-legend" open>
    <summary>Legende · Areale ein-/ausblenden</summary>
    <div class="legend-actions">
      <button id="show-regions" disabled>Alle anzeigen</button>
      <button id="hide-regions" disabled>Alle ausblenden</button>
    </div>
    <p id="region-count" class="hint" role="status">Areal-Legende wird geladen …</p>
    <ul id="region-list">
      {% for region in meshes %}
      {% if region.selectable %}
      <li>
        <label class="region-row" for="region-{{ loop.index0 }}" title="{{ region.region_id }}">
          <input id="region-{{ loop.index0 }}" type="checkbox" {% if region.default_visible %}checked{% endif %} disabled>
          <span id="region-color-{{ loop.index0 }}" class="region-color" aria-hidden="true"></span>
          <span class="region-name">{{ region.name }}</span>
          <span id="region-state-{{ loop.index0 }}" class="region-state">Lädt …</span>
        </label>
      </li>
      {% endif %}
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
    <p class="hint">Gefüllte Schnitte benötigen zusätzliche Grafikleistung. Nur geometrisch geprüfte Regionen erhalten Schnittflächen.</p>
    {% if cut_excluded %}<p class="hint" id="cut-validation-status">{{ cut_excluded }} Regionen ohne verlässlich geprüfte Schnittfläche; ihre Originalgeometrie bleibt auswählbar.</p>{% endif %}
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
<script id="mri-region-list" type="application/json">{{ mri_regions|tojson }}</script>
<script id="mesh-list" type="application/json">{{ meshes|tojson }}</script>
<script id="region-groups" type="application/json">{{ groups|tojson }}</script>
<script id="region-aliases" type="application/json">{{ aliases|tojson }}</script>
<script id="focus-context-opacities" type="application/json">{{ focus_context_opacities|tojson }}</script>
<script>
  import({{ url_for('static', filename='viewer_app.js')|tojson }}).catch((error) => {
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
@app.route("/mri")
def index():
    if request.path == "/mri":
        from main.region_groups import groups_for_ids
        from main.mesh_catalog import aliases_for_ids
        ids = mri_store.catalog()['regions']
        return render_template_string(HTML, meshes=[], count=0, mesh_detail='optimized',
            groups=groups_for_ids(ids), aliases=aliases_for_ids(ids), cut_excluded=0,
            focus_context_opacities=FOCUS_CONTEXT_OPACITIES, preview_triangles='–',
            initial_viewer='mri', mri_regions=mri_regions())
    regions = [region for region in load_regions(MESH_DIR) if region['renderable']]
    validation = cut_validation(MESH_DIR, regions)
    meshes = [{**region, **validation[region['region_id']],
               'glb_url': '/mesh/' + region['mesh_glb'] + '?v=' + validation[region['region_id']]['mesh_sha256']}
              for region in regions]
    preview_count = sum(int(region.get('triangles_optimized') or 0) for region in meshes)
    triangle_label = lambda count: f'{count:,}'.replace(',', chr(0x2019)) if count else '–'
    return render_template_string(
        HTML, meshes=meshes, count=len(meshes), mesh_detail='optimized',
        groups=region_groups(MESH_DIR), aliases=selection_aliases(MESH_DIR),
        cut_excluded=sum(not region['cut_eligible'] for region in meshes),
        focus_context_opacities=FOCUS_CONTEXT_OPACITIES,
        preview_triangles=triangle_label(preview_count), initial_viewer='mesh', mri_regions=mri_regions())

@app.get('/api/mesh-catalog')
def mesh_catalog_payload():
    regions = [region for region in load_regions(MESH_DIR) if region['renderable']]
    validation = cut_validation(MESH_DIR, regions)
    return {'meshes': [{**region, **validation[region['region_id']],
        'glb_url': '/mesh/' + region['mesh_glb'] + '?v=' + validation[region['region_id']]['mesh_sha256']}
        for region in regions]}


@app.route("/mesh/<path:filename>")
def mesh(filename):
    if filename not in available_mesh_names(MESH_DIR):
        abort(404)
    detail = request.args.get('detail', 'optimized')
    if detail not in ('optimized', 'full'):
        abort(400)
    if detail == 'full':
        abort(404)
    return send_from_directory(MESH_DIR, filename, mimetype='model/gltf-binary',
                               conditional=True, max_age=3600)

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
