from pathlib import Path
from flask import Flask, render_template_string, send_from_directory
import os
import secrets

# Support both `python -m main.brain_viewer` and IDEs that execute this file
# directly. Direct execution otherwise places only `main/` on sys.path.
if __package__ in (None, ''):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from main.brain_assistant import create_assistant
else:
    from .brain_assistant import create_assistant

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MESH_DIR = PROJECT_ROOT / "export_preview"
app = Flask(__name__, static_folder=str(PROJECT_ROOT / "static"), static_url_path="/static")
app.secret_key = os.environ.get('BRAIN_VIEWER_SESSION_SECRET') or secrets.token_hex(32)
app.config.update(MAX_CONTENT_LENGTH=11 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
app.register_blueprint(create_assistant(MESH_DIR))

HTML = r"""
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Gehirn Viewer</title>
  <link rel="icon" href="data:,">
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
      "three": "https://cdn.jsdelivr.net/npm/three@0.152.2/build/three.module.js",
      "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.152.2/examples/jsm/"
    }}
  </script>
</head>
<body>
<header class="app-header"><div><span class="brand-icon" aria-hidden="true">◉</span> NEURO<span class="brand-light">ATLAS</span></div><div class="header-actions"><span class="app-caption">Das Gehirn entdecken</span><button id="fullscreen-toggle" type="button" aria-pressed="false">Vollbild</button></div></header>
<p id="fullscreen-status" role="status" hidden></p>
<div id="scene" aria-label="Interaktives 3D-Gehirn"></div>
<div id="info">
  <h3>Gehirn – alle Regionen</h3>
  <p id="status" role="status">{{ count }} Regionen gefunden – 3D-Ansicht wird gestartet …</p>
  <p class="hint">Ziehen: drehen · Zwei Finger: zoomen &amp; verschieben · Am PC: Mausrad zum Zoomen</p>
  <button id="reset" disabled>Ansicht zurücksetzen</button>
  <p><label class="rotation-option"><input id="auto-rotate" type="checkbox" checked> Langsam drehen</label></p>
  <label>Bildauflösung
    <select id="resolution"><option value="0.75">Sparsam</option><option value="1" selected>Standard</option><option value="native">Hoch (Displayauflösung)</option></select>
  </label>
  <p class="hint">Optimierte 3D-Geometrie · Für weniger Grafiklast die Drehung ausschalten.</p>
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
          <input id="region-{{ loop.index0 }}" type="checkbox" checked disabled>
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
    <p class="hint">Je Achse bleibt der Bereich zwischen Von und Bis sichtbar.</p>
    {% for axis, description in [('x', 'links ↔ rechts'), ('y', 'hinten ↔ vorne'), ('z', 'unten ↔ oben')] %}
    <fieldset disabled id="cut-{{ axis }}">
      <legend>{{ axis|upper }} · {{ description }}</legend>
      {% for bound, label, value in [('min', 'Von', 0), ('max', 'Bis', 100)] %}
      <label for="{{ axis }}-{{ bound }}">
        <span>{{ label }}</span>
        <input id="{{ axis }}-{{ bound }}" type="range" min="0" max="100" step="0.1" value="{{ value }}" aria-label="{{ axis|upper }} {{ label }}">
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
    <div class="assistant-options">
      <label><input id="assistant-web" type="checkbox" checked> Websuche</label>
      <label><input id="assistant-speak" type="checkbox" checked> Vorlesen</label>
      <label>Stimme <select id="assistant-voice"><option value="marin">Marin</option><option value="cedar">Cedar</option></select></label>
    </div>
    <div class="assistant-options">
      <button id="assistant-send" disabled>Senden</button>
      <button id="assistant-mic" type="button" disabled aria-pressed="false">Mikrofon starten</button>
      <button id="assistant-new" type="button">Neues Gespräch</button>
      <button id="clear-highlight" type="button">Markierung löschen</button>
    </div>
  </form>
  <div class="assistant-options"><button id="realtime-start" type="button" disabled aria-pressed="false">Realtime starten</button><button id="realtime-interrupt" type="button" disabled>Antwort unterbrechen</button></div>
  <p id="realtime-status" role="status" class="hint">Live-Sprachgespräch · Starten und frei sprechen. Stoppen schaltet das Mikrofon aus.</p>
  <p class="hint">Realtime überträgt Audio während der Verbindung an OpenAI und antwortet mit KI-Stimme. Jedes Starten beginnt ein eigenes Sprachgespräch. Stimme und Websuche vorher auswählen.</p>
  <audio id="realtime-audio" controls hidden aria-label="Realtime-Sprachausgabe"></audio>
  <details class="usage-panel" open>
    <summary>Verbrauch &amp; Limits</summary>
    <p id="realtime-usage" class="hint">Noch kein Realtime-Verbrauch gemeldet.</p>
    <div id="realtime-limits" aria-label="Zuletzt gemeldete Rate-Limits"><p class="hint">Noch keine Limitdaten.</p></div>
    <p class="hint">Tokens dieser Realtime-Sitzung, aktualisiert nach jeder Antwort, inklusive gemeldeter abgebrochener Antworten. Cache-Tokens sind bereits in der Eingabe enthalten. Neustart setzt den Zähler zurück, nicht die API-Limits. Nach einem kurzfristigen Rate-Limit wartet die App bis zur gemeldeten Reset-Zeit und versucht die letzte Antwort einmal erneut. Textchat, separate Transkription, Webrecherche und andere Geräte sind hier nicht mitgezählt.</p>
    <p class="hint">Kontostand: hier nicht abrufbar. <a href="https://platform.openai.com/settings/organization/billing/overview" target="_blank" rel="noopener noreferrer">Guthaben bei OpenAI öffnen ↗</a></p>
    <a href="https://platform.openai.com/settings/organization/limits" target="_blank" rel="noopener noreferrer">Kontolimits ansehen ↗</a>
  </details>
  <div class="assistant-options"><button id="speech-stop" type="button" disabled>Sprachausgabe stoppen</button></div>
  <p id="speech-status" role="status" class="hint">KI-generierte Stimme · OpenAI</p>
  <audio id="assistant-audio" controls hidden aria-label="Gesprochene Antwort"></audio>
  <p class="hint">Mikrofon starten → sprechen → Stoppen &amp; senden. Maximal 60 Sekunden. Audio und Fragen werden zur Verarbeitung an OpenAI gesendet; die 3D-Dateien bleiben lokal.</p>
</details>
<nav class="mobile-nav" aria-label="Ansicht wählen">
  <button type="button" data-panel="scene" aria-pressed="true">3D-Ansicht</button>
  <button type="button" data-panel="regions" aria-controls="info" aria-pressed="false">Areale &amp; Schnitte</button>
  <button type="button" data-panel="assistant" aria-controls="assistant-panel" aria-pressed="false">Assistent</button>
</nav>
<script type="module" src="{{ url_for('static', filename='viewer_ui.js') }}"></script>
<script id="mesh-list" type="application/json">{{ meshes|tojson }}</script>
<script>
  import({{ url_for('static', filename='brain_viewer.js')|tojson }}).catch((error) => {
    document.getElementById('status').textContent = '3D-Ansicht konnte nicht gestartet werden.';
    const item = document.createElement('li');
    item.textContent = 'Bitte Internetverbindung und WebGL prüfen: ' + error.message;
    document.getElementById('errors').appendChild(item);
    console.error(error);
  });
</script>
</body>
</html>
"""

@app.route("/")
def index():
    meshes = sorted(p.name for p in MESH_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".obj")
    return render_template_string(HTML, meshes=meshes, count=len(meshes))

@app.route("/mesh/<path:filename>")
def mesh(filename):
    return send_from_directory(MESH_DIR, filename)

if __name__ == "__main__":
    print(f"Serving surface files from: {MESH_DIR}")
    app.run(host=os.environ.get('BRAIN_VIEWER_HOST', '127.0.0.1'), port=5000, debug=False)
