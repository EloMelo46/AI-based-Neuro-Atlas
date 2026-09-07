import { initMicrophone } from './microphone.js';
import { initSpeech } from './speech.js';
import { initRealtime } from './realtime.js';

export async function initAssistant(viewer) {
  const status = document.getElementById('assistant-status');
  const log = document.getElementById('assistant-messages');
  const input = document.getElementById('assistant-input');
  const send = document.getElementById('assistant-send');
  const reset = document.getElementById('assistant-new');
  const availability = document.createElement('p');
  availability.className = 'hint';
  availability.setAttribute('role', 'status');
  document.getElementById('assistant-form').appendChild(availability);
  if (['assistant-audio', 'speech-status', 'speech-stop', 'assistant-voice', 'realtime-start', 'realtime-status', 'realtime-audio'].some(id => !document.getElementById(id))) {
    const reason = 'Veraltete Serverseite: Python-Server mit Strg+C stoppen, neu starten und danach Strg+F5 drücken.';
    status.textContent = reason;
    availability.textContent = reason;
    send.title = reason;
    document.getElementById('assistant-mic').title = reason;
    return;
  }
  let busy = false;
  let configured = false;
  let microphone = null;
  let realtime = null;
  const speech = initSpeech();

  function message(text, kind = '') {
    const row = document.createElement('div');
    row.className = `assistant-message ${kind}`;
    row.textContent = text;
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
    return row;
  }
  function answer(part) {
    const row = message('');
    const chars = Array.from(part.text);
    let offset = 0;
    for (const cite of [...part.citations].sort((a, b) => a.start_index - b.start_index)) {
      if (!Number.isInteger(cite.start_index) || !Number.isInteger(cite.end_index) || cite.start_index < offset || cite.end_index > chars.length) continue;
      const url = new URL(cite.url);
      if (!['https:', 'http:'].includes(url.protocol)) continue;
      row.appendChild(document.createTextNode(chars.slice(offset, cite.start_index).join('')));
      const link = document.createElement('a');
      link.href = url.href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = chars.slice(cite.start_index, cite.end_index).join('') || cite.title || 'Quelle';
      link.title = cite.title || 'Quelle';
      row.appendChild(link);
      offset = cite.end_index;
    }
    row.appendChild(document.createTextNode(chars.slice(offset).join('')));
    log.scrollTop = log.scrollHeight;
  }
  async function post(path, body) {
    const response = await fetch(path, { method: 'POST', headers: {
      'Content-Type': 'application/json', 'X-Brain-Viewer': '1',
    }, body: JSON.stringify(body), signal: AbortSignal.timeout(180000) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Anfrage fehlgeschlagen.');
    return data;
  }
  function setBusy(value) {
    busy = value;
    document.getElementById('assistant-form').setAttribute('aria-busy', String(value));
    send.disabled = value || !configured;
    reset.disabled = value;
    input.disabled = value;
    microphone?.setAvailable(!value && configured);
    realtime?.setAvailable(!value && configured);
  }
  realtime = initRealtime({ viewer, message, answer, onActive(value) {
    if (value) speech.stop();
    setBusy(value);
    document.getElementById('assistant-form').setAttribute('aria-busy', 'false');
    status.textContent = value ? 'Realtime-Sprachgespräch aktiv · Textchat pausiert.' : 'Bereit.';
    for (const id of ['assistant-voice', 'assistant-web', 'assistant-speak']) document.getElementById(id).disabled = value;
  } });
  microphone = initMicrophone({ button: document.getElementById('assistant-mic'), status, setBusy, onStart: speech.stop,
    onText(text) {
      input.value = text;
      document.getElementById('assistant-form').requestSubmit();
    },
    onError(text) { message(text, 'error'); status.textContent = 'Mikrofoneingabe fehlgeschlagen.'; },
  });
  document.getElementById('clear-highlight').addEventListener('click', () => {
    viewer.execute({ name: 'highlight_regions', arguments: { region_ids: [] } });
  });
  reset.addEventListener('click', async () => {
    if (busy) return;
    speech.stop();
    setBusy(true);
    try {
      await post('/api/assistant/reset', {});
      log.replaceChildren();
      status.textContent = 'Neues Gespräch gestartet.';
    } catch (error) { message(error.message, 'error'); }
    finally { setBusy(false); }
  });
  document.getElementById('assistant-form').addEventListener('submit', async event => {
    event.preventDefault();
    const question = input.value.trim();
    if (busy || !configured || !question) return;
    message(question, 'user');
    input.value = '';
    setBusy(true);
    speech.stop();
    status.textContent = 'Der Assistent arbeitet …';
    try {
      let data = await post('/api/assistant/chat', { message: question, state: viewer.getState(),
        web_search: document.getElementById('assistant-web').checked });
      for (let round = 0; data.actions.length && round < 7; round++) {
        const results = [];
        for (const action of data.actions) {
          try {
            viewer.execute(action);
            results.push({ call_id: action.call_id, ok: true });
            message(viewer.describe(action), 'action');
          } catch (error) {
            results.push({ call_id: action.call_id, ok: false, error: error.message });
            message(error.message, 'error');
          }
        }
        data = await post('/api/assistant/chat', { turn_id: data.turn_id, results, state: viewer.getState() });
      }
      if (data.actions.length) throw new Error('Aktionslimit erreicht. Bitte neues Gespräch starten.');
      data.messages.forEach(answer);
      if (document.getElementById('assistant-speak').checked) speech.speak(data.messages, document.getElementById('assistant-voice').value);
      status.textContent = 'Bereit.';
    } catch (error) {
      message(error.message + ' Falls Aktionen bereits ausgeführt wurden, bleiben sie bestehen. Bei Verbindungsabbruch bitte ein neues Gespräch starten.', 'error');
      status.textContent = 'Anfrage fehlgeschlagen.';
    } finally { setBusy(false); input.focus(); }
  });
  try {
    const response = await fetch('/api/assistant/config', { cache: 'no-store', signal: AbortSignal.timeout(10000) });
    if (!response.ok) throw new Error('Assistent-Konfiguration nicht erreichbar.');
    const config = await response.json();
    configured = config.configured;
    status.textContent = configured ? `Bereit · ${config.model}` : 'OPENAI_API_KEY auf dem Server setzen und neu starten.';
    availability.textContent = configured ? '' : 'Senden und Mikrofon sind gesperrt: OPENAI_API_KEY fehlt im laufenden Python-Server.';
    setBusy(false);
  } catch (error) {
    status.textContent = error.message;
    availability.textContent = 'Assistent nicht bereit: Serververbindung prüfen und Seite neu laden. ' + error.message;
  }
}
