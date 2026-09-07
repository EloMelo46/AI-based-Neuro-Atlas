import { initRealtimeUsage } from './realtime_usage.js';

export function initRealtime({ viewer, message, answer, onActive }) {
  const metrics = initRealtimeUsage();
  const button = document.getElementById('realtime-start');
  const status = document.getElementById('realtime-status');
  const audio = document.getElementById('realtime-audio');
  const interruptButton = document.getElementById('realtime-interrupt');
  let current = null;
  let available = false;
  function stop(reason = 'Sprachgespräch beendet. Mikrofon aus.') {
    metrics.stop();
    const old = current;
    current = null;
    if (old) {
      clearTimeout(old.timer);
      clearTimeout(old.disconnectTimer);
      clearTimeout(old.retryTimer);
      clearInterval(old.retryTicker);
      old.abort.abort();
      old.stream?.getTracks().forEach(track => track.stop());
      old.channel?.close();
      old.pc?.close();
    }
    audio.pause();
    audio.srcObject = null;
    audio.hidden = true;
    if (interruptButton) interruptButton.disabled = true;
    button.textContent = 'Realtime starten';
    button.setAttribute('aria-pressed', 'false');
    status.textContent = reason;
    onActive(false);
    button.disabled = !available;
  }
  async function post(path, body, run) {
    const response = await fetch(path, { method: 'POST', headers: {
      'Content-Type': 'application/json', 'X-Brain-Viewer': '1',
    }, body: JSON.stringify(body), signal: AbortSignal.any([run.abort.signal, AbortSignal.timeout(90000)]) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Realtime-Anfrage fehlgeschlagen.');
    return data;
  }
  function send(run, event) {
    if (current === run && run.channel.readyState === 'open') run.channel.send(JSON.stringify(event));
  }
  function cancelRetry(run) {
    clearTimeout(run.retryTimer);
    clearInterval(run.retryTicker);
    run.retryTimer = null;
    run.retryTicker = null;
  }
  function scheduleRateLimitRetry(run) {
    const turn = run.turn;
    if (run.retryAttempts.has(turn)) return '';
    run.retryAttempts.add(turn);
    const delay = metrics.retryDelayMs() ?? 5000;
    const retryAt = Date.now() + delay;
    const update = () => {
      if (current !== run || run.turn !== turn) return;
      const seconds = Math.max(1, Math.ceil((retryAt - Date.now()) / 1000));
      status.textContent = `${run.notice} Automatischer neuer Versuch in ca. ${seconds} s.`;
    };
    update();
    run.retryTicker = setInterval(update, 1000);
    run.retryTimer = setTimeout(() => {
      cancelRetry(run);
      if (current !== run || run.turn !== turn || run.channel.readyState !== 'open') return;
      status.textContent = 'Limit-Reset erreicht · Anfrage wird automatisch erneut gesendet …';
      send(run, { type: 'response.create' });
    }, delay);
    return ` Automatischer neuer Versuch in ca. ${Math.max(1, Math.ceil(delay / 1000))} s.`;
  }
  function reportError(run, detail = {}, prefix = 'Realtime-Antwort fehlgeschlagen') {
    detail = detail || {};
    const code = detail.code || detail.type || 'unknown_error';
    const hints = {
      server_error: 'OpenAI konnte die Antwort nicht erzeugen. Bitte erneut fragen.',
      rate_limit_exceeded: 'OpenAI-Anfragelimit erreicht. Bitte kurz warten und erneut fragen.',
      insufficient_quota: 'OpenAI-Kontingent aufgebraucht. Bitte Abrechnung und Limits prüfen.',
    };
    const apiDetail = typeof detail.message === 'string' ? detail.message.trim().slice(0, 1500) : '';
    const hint = hints[code];
    const explanation = hint ? `${hint}${apiDetail ? ` OpenAI: ${apiDetail}` : ''}`
      : apiDetail || 'OpenAI hat keinen genaueren Fehlergrund übermittelt.';
    const limits = metrics.describeLimits();
    run.notice = `${prefix}: ${explanation} (${code})${limits ? ` ${limits}.` : ''} Verbindung bleibt offen; Mikrofon ist weiter aktiv.`;
    status.textContent = run.notice;
    message(run.notice, 'error');
    if (code === 'rate_limit_exceeded') scheduleRateLimitRetry(run);
  }
  async function handle(run, event) {
    if (current !== run) return;
    metrics.handle(event);
    if (event.type === 'error') {
      // A response can finish between clicking interrupt and server receipt.
      if (event.error?.code === 'response_cancel_not_active') return;
      reportError(run, event.error, 'Realtime-Fehler');
      return;
    }
    if (event.type === 'response.created') {
      cancelRetry(run);
      run.responseId = event.response.id;
      run.notice = null;
    }
    if (event.type === 'response.done' && run.responseId === event.response.id) run.responseId = null;
    if (event.type === 'output_audio_buffer.started') {
      audio.muted = false;
    }
    if (event.type === 'input_audio_buffer.speech_started') {
      cancelRetry(run);
      run.notice = null;
      run.rounds = 0;
      run.turn++;
      status.textContent = 'Ich höre zu …';
    }
    if (event.type === 'input_audio_buffer.speech_stopped') status.textContent = 'Antwort wird vorbereitet …';
    if (event.type === 'conversation.item.input_audio_transcription.completed') message(event.transcript, 'user');
    if (event.type === 'response.output_audio_transcript.delta') {
      if (!run.rows.has(event.item_id)) run.rows.set(event.item_id, message(''));
      run.rows.get(event.item_id).textContent += event.delta;
      status.textContent = 'Der Assistent spricht …';
    }
    if (event.type === 'output_audio_buffer.stopped' && !run.notice) status.textContent = 'Verbunden · Du kannst sprechen.';
    if (event.type !== 'response.done') return;
    if (event.response.status === 'failed') {
      reportError(run, event.response.status_details?.error);
      return;
    }
    if (event.response.status === 'incomplete') {
      reportError(run, { code: event.response.status_details?.reason || 'incomplete',
        message: 'Die Antwort wurde nicht vollständig erzeugt. Bitte kürzer oder erneut fragen.' });
      return;
    }
    if (event.response.status !== 'completed') return;
    const calls = (event.response.output || []).filter(item => item.type === 'function_call');
    const turn = run.turn;
    for (const call of calls) {
      if (run.seen.has(call.call_id)) continue;
      run.seen.add(call.call_id);
      let result;
      try {
        if (++run.rounds > 12) throw new Error('Aktionslimit erreicht. Bitte eine neue Frage stellen.');
        status.textContent = call.name === 'search_web' ? 'Ich recherchiere …' : 'Ansicht wird angepasst …';
        result = await post('/api/assistant/realtime/tool', { name: call.name,
          arguments: JSON.parse(call.arguments), state: viewer.getState(),
          web_search: document.getElementById('assistant-web').checked }, run);
        if (current !== run) return;
        if (turn !== run.turn) throw new Error('Durch neue Spracheingabe unterbrochen. Aktion nicht ausgeführt.');
        if (result.action) {
          viewer.execute(result.action);
          message(viewer.describe(result.action), 'action');
          result = { ok: true, state: viewer.getState() };
        }
        result.messages?.forEach(answer);
      } catch (error) {
        if (current !== run) return;
        result = { ok: false, error: error.message };
        message(error.message, 'error');
      }
      send(run, { type: 'conversation.item.create', item: {
        type: 'function_call_output', call_id: call.call_id, output: JSON.stringify(result),
      } });
    }
    if (calls.length && current === run && turn === run.turn) {
      send(run, { type: 'response.create', response: run.rounds >= 12 ? { tool_choice: 'none' } : {} });
    }
  }
  async function start() {
    metrics.reset();
    const run = { abort: new AbortController(), rows: new Map(), seen: new Set(),
      retryAttempts: new Set(), rounds: 0, turn: 0 };
    current = run;
    onActive(true);
    button.disabled = false;
    button.textContent = 'Realtime stoppen';
    button.setAttribute('aria-pressed', 'true');
    status.textContent = 'Mikrofon freigeben · Verbindung wird aufgebaut …';
    run.timer = setTimeout(() => { if (current === run) stop('Verbindungsaufbau dauert zu lange. Bitte erneut starten.'); }, 45000);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      if (current !== run) { stream.getTracks().forEach(track => track.stop()); return; }
      run.stream = stream;
      const pc = run.pc = new RTCPeerConnection();
      pc.ontrack = event => {
        if (current !== run) return;
        audio.srcObject = event.streams[0] || new MediaStream([event.track]);
        audio.hidden = false;
        audio.play().catch(() => { if (current === run) status.textContent = 'Bitte Play am Audioplayer anklicken.'; });
      };
      pc.onconnectionstatechange = () => {
        if (current !== run) return;
        if (pc.connectionState !== 'disconnected') {
          clearTimeout(run.disconnectTimer);
          run.disconnectTimer = null;
        }
        if (pc.connectionState === 'connected') {
          return;
        }
        if (pc.connectionState === 'disconnected') {
          if (run.disconnectTimer) return;
          status.textContent = 'Verbindung kurz unterbrochen · Wiederverbindung läuft …';
          run.disconnectTimer = setTimeout(() => {
            if (current === run && pc.connectionState === 'disconnected') {
              stop('Realtime-Verbindung blieb 10 Sekunden unterbrochen. Bitte erneut starten.');
            }
          }, 10000);
          return;
        }
        if (pc.connectionState === 'failed') {
          stop('WebRTC-Verbindung endgültig fehlgeschlagen. Netzwerk, VPN oder Firewall prüfen.');
        } else if (pc.connectionState === 'closed') {
          stop('Sprachverbindung geschlossen.');
        }
      };
      stream.getTracks().forEach(track => {
        pc.addTrack(track, stream);
        track.onended = () => { if (current === run) stop('Mikrofon wurde getrennt.'); };
      });
      const channel = run.channel = pc.createDataChannel('oai-events');
      channel.onopen = () => {
        if (current !== run) return;
        clearTimeout(run.timer);
        run.stage = 'verbunden';
        if (interruptButton) interruptButton.disabled = false;
        status.textContent = 'Verbunden · Mikrofon an · Du kannst sprechen.';
      };
      channel.onclose = () => { if (current === run) stop('Sprachverbindung geschlossen.'); };
      channel.onmessage = event => {
        Promise.resolve().then(() => handle(run, JSON.parse(event.data))).catch(error => {
          if (current === run) { message(error.message, 'error'); stop(error.message); }
        });
      };
      run.stage = 'temporären Sitzungsschlüssel erstellen';
      const data = await post('/api/assistant/realtime/session', { state: viewer.getState(),
        voice: document.getElementById('assistant-voice').value,
        web_search: document.getElementById('assistant-web').checked }, run);
      if (current !== run) return;
      run.stage = 'lokales SDP-Angebot erstellen';
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      run.stage = 'WebRTC-Aufruf zu OpenAI';
      const response = await fetch('https://api.openai.com/v1/realtime/calls', {
        method: 'POST', body: offer.sdp,
        headers: { Authorization: `Bearer ${data.value}`, 'Content-Type': 'application/sdp' },
        signal: run.abort.signal,
      });
      if (!response.ok) {
        const failure = await response.json().catch(() => ({}));
        const detail = failure.error || {};
        const fallback = response.status === 429
          ? 'OpenAI-Limit oder Kontingent erreicht. Limits und Abrechnung prüfen.'
          : 'Modellzugriff und Berechtigungen prüfen.';
        const reason = typeof detail.message === 'string' ? detail.message.slice(0, 1500) : fallback;
        const code = typeof detail.code === 'string' ? ` · ${detail.code}` : '';
        const retry = response.headers.get('retry-after');
        throw new Error(`Realtime-Verbindung abgelehnt (${response.status}${code}): ${reason}` +
          (retry ? ` Wiederholung laut OpenAI frühestens nach: ${retry}.` : ''));
      }
      const sdp = await response.text();
      if (current !== run) return;
      run.stage = 'OpenAI-SDP-Antwort übernehmen';
      await pc.setRemoteDescription({ type: 'answer', sdp });
    } catch (error) {
      if (current !== run) return;
      console.error(`[realtime] Fehler in Phase „${run.stage || 'Mikrofonzugriff'}“`, error);
      const reason = error.name === 'NotAllowedError'
        ? 'Mikrofonzugriff verweigert. Bitte im Browser erlauben.'
        : error.message || String(error);
      stop(`${reason} · Phase: ${run.stage || 'Mikrofonzugriff'}`);
    }
  }
  button.addEventListener('click', () => current ? stop() : start());
  interruptButton?.addEventListener('click', () => {
    const run = current;
    if (!run || run.channel?.readyState !== 'open') return;
    // Mute immediately while the server discards queued audio and truncates it.
    audio.muted = true;
    run.turn++;
    cancelRetry(run);
    if (run.responseId) send(run, { type: 'response.cancel', response_id: run.responseId });
    send(run, { type: 'output_audio_buffer.clear' });
    status.textContent = 'Antwort unterbrochen · Mikrofon bleibt an · Du kannst sprechen.';
  });
  window.addEventListener('pagehide', () => stop());
  return { stop, setAvailable(value) {
    available = value && window.isSecureContext && !!navigator.mediaDevices?.getUserMedia && !!window.RTCPeerConnection;
    button.disabled = !current && !available;
    if (value && !available) status.textContent = 'Realtime benötigt einen Browser mit WebRTC und localhost oder HTTPS.';
  } };
}
