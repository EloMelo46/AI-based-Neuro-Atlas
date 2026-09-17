import { initMicrophone } from './microphone.js';
import { initSpeech } from './speech.js';
import { initMentionCues } from './region_mentions.js';

export async function initAssistant(viewer) {
  const status = document.getElementById('assistant-status');
  const log = document.getElementById('assistant-messages');
  const input = document.getElementById('assistant-input');
  const send = document.getElementById('assistant-send');
  const reset = document.getElementById('assistant-new');
  if (['assistant-audio', 'assistant-voice', 'assistant-speak', 'assistant-mic'].some(id => !document.getElementById(id))) {
    const reason = 'Veraltete Serverseite: Python-Server mit Strg+C stoppen, neu starten und danach Strg+F5 drücken.';
    status.textContent = reason;
    send.title = reason;
    document.getElementById('assistant-mic').title = reason;
    return;
  }
  let busy = false;
  let configured = false;
  let microphone = null;
  let requestController = null;
  let interrupted = false;
  const mentions = initMentionCues(viewer);
  const speech = initSpeech({
    onError(text) { message(text, 'error'); },
    onCue: mentions.glow, onStop: mentions.stop,
    getRegionIds: () => viewer.getState().loaded,
  });

  function message(text, kind = '') {
    const row = document.createElement('div');
    row.className = `assistant-message ${kind}`;
    row.textContent = text;
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
    return row;
  }
  function answer(part, existingRow = null) {
    const row = existingRow || message('');
    row.replaceChildren();
    row.classList.remove('streaming');
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
  async function post(path, body, timeoutMs = 180000) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    let response;
    try {
      response = await fetch(path, { method: 'POST', headers: {
        'Content-Type': 'application/json', 'X-Brain-Viewer': '1',
      }, body: JSON.stringify(body), signal: controller.signal });
    } finally { clearTimeout(timeout); }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Anfrage fehlgeschlagen.');
    return data;
  }
  async function streamChat(path, body, onDelta, signal) {
    const response = await fetch(path, { method: 'POST', headers: {
      'Content-Type': 'application/json', 'X-Brain-Viewer': '1',
    }, body: JSON.stringify(body), signal });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.error || 'Anfrage fehlgeschlagen.');
    }
    const reader = response.body?.getReader();
    if (!reader) throw new Error('Dieser Browser unterstützt keinen Textstream.');
    const decoder = new TextDecoder();
    let buffer = '';
    let result = null;
    function consume(raw) {
      if (!raw.trim()) return;
      const event = JSON.parse(raw);
      if (event.type === 'delta') onDelta(event.text || '');
      else if (event.type === 'result') result = event.data;
      else if (event.type === 'error') throw new Error(event.error || 'Anfrage fehlgeschlagen.');
      else if (event.type === 'cancelled') throw new DOMException('Antwort unterbrochen', 'AbortError');
    }
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const raw of lines) consume(raw);
      if (done) break;
    }
    consume(buffer);
    if (!result) throw new Error('Der Antwortstream endete unerwartet.');
    return result;
  }
  function setBusy(value) {
    busy = value;
    document.getElementById('assistant-form').setAttribute('aria-busy', String(value));
    send.disabled = value || !configured;
    reset.disabled = value;
    input.disabled = value;
    microphone?.setAvailable(!value && configured);
  }
  function interruptResponse() {
    if (!requestController) return;
    interrupted = true;
    requestController.abort();
    speech.stop();
    status.textContent = 'Antwort wird unterbrochen …';
    void post('/api/assistant/cancel', {}, 10000).catch(() => {});
  }
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !document.fullscreenElement && !document.body.classList.contains('viewer-fullscreen')) {
      if (requestController) interruptResponse();
      else speech.stop();
    }
  });
  microphone = initMicrophone({ button: document.getElementById('assistant-mic'), status, setBusy, onStart: speech.stop,
    onText(text) {
      input.value = text;
      document.getElementById('assistant-form').requestSubmit();
    },
    onError(text) { message(text, 'error'); status.textContent = 'Mikrofoneingabe fehlgeschlagen.'; },
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
    interrupted = false;
    requestController = new AbortController();
    const timeout = setTimeout(() => requestController?.abort(), 180000);
    let streamedRow = null;
    try {
      const request = body => streamChat('/api/assistant/chat', body, delta => {
        if (!streamedRow) streamedRow = message('', 'streaming');
        streamedRow.appendChild(document.createTextNode(delta));
        log.scrollTop = log.scrollHeight;
        status.textContent = 'Antwort wird übertragen …';
      }, requestController.signal);
      let data = await request({ message: question, state: viewer.getState() });
      for (let round = 0; data.actions.length && round < 7; round++) {
        const results = [];
        for (const action of data.actions) {
          try {
            const state = viewer.execute(action);
            results.push({ call_id: action.call_id, ok: true, state });
            message(viewer.describe(action), 'action');
          } catch (error) {
            results.push({ call_id: action.call_id, ok: false, error: error.message });
            message(error.message, 'error');
          }
        }
        data = await request({ turn_id: data.turn_id, results, state: viewer.getState() });
      }
      if (data.actions.length) throw new Error('Aktionslimit erreicht. Bitte neues Gespräch starten.');
      data.messages.forEach((part, index) => answer(part, index === 0 ? streamedRow : null));
      if (document.getElementById('assistant-speak').checked) speech.speak(data.messages, document.getElementById('assistant-voice').value);
      else mentions.showText(data.messages);
      status.textContent = 'Bereit.';
    } catch (error) {
      streamedRow?.classList.remove('streaming');
      if (error.name === 'AbortError') {
        if (!interrupted) {
          void post('/api/assistant/cancel', {}, 10000).catch(() => {});
          message('Zeitlimit der Anfrage erreicht.', 'error');
        }
        status.textContent = interrupted ? 'Antwort unterbrochen.' : 'Anfrage fehlgeschlagen.';
      } else {
        message(error.message + ' Falls Aktionen bereits ausgeführt wurden, bleiben sie bestehen. Bei Verbindungsabbruch bitte ein neues Gespräch starten.', 'error');
        status.textContent = 'Anfrage fehlgeschlagen.';
      }
    } finally {
      clearTimeout(timeout);
      requestController = null;
      setBusy(false);
      if (!document.fullscreenElement) input.focus();
    }
  });
  try {
    const response = await fetch('/api/assistant/config', { cache: 'no-store', signal: AbortSignal.timeout(10000) });
    if (!response.ok) throw new Error('Assistent-Konfiguration nicht erreichbar.');
    const config = await response.json();
    configured = config.configured;
    status.textContent = configured ? 'Bereit.' : 'OPENAI_API_KEY auf dem Server setzen und neu starten.';
    setBusy(false);
  } catch (error) {
    status.textContent = error.message;
  }
}
