export function initMicrophone({ button, status, setBusy, onText, onError, onStart, onRecordingChange }) {
  let available = false;
  let capture = null;
  let recordingShown = false;
  const supported = window.isSecureContext && navigator.mediaDevices?.getUserMedia && window.MediaRecorder;
  const hint = document.getElementById('assistant-mic-hint');
  const unavailableReason = !window.isSecureContext
    ? 'Mikrofon gesperrt: Öffne Neuro Atlas lokal über localhost. Der Textchat bleibt verfügbar.'
    : !supported
      ? 'Dieser Browser unterstützt keine Mikrofonaufnahme. Verwende einen aktuellen Browser. Der Textchat bleibt verfügbar.'
      : '';
  if (hint) {
    hint.textContent = unavailableReason;
    hint.hidden = !unavailableReason;
  }
  function refresh() {
    const phase = capture?.phase || 'idle';
    const recording = phase === 'recording';
    button.disabled = !supported || (phase === 'idle' ? !available : !recording);
    button.textContent = recording ? 'Stoppen & senden' : 'Mikrofon starten';
    button.setAttribute('aria-pressed', String(recording));
    if (recordingShown !== recording) {
      recordingShown = recording;
      onRecordingChange?.(recording);
    }
  }
  function release(current) {
    clearInterval(current.timer);
    current.stream?.getTracks().forEach(track => track.stop());
    current.stream = null;
  }
  function finish(current) {
    release(current);
    if (capture !== current) return;
    capture = null;
    setBusy(false);
    refresh();
  }
  function fail(current, message) {
    if (capture !== current || current.cancelled) return;
    current.cancelled = true;
    if (current.recorder?.state === 'recording') current.recorder.stop();
    finish(current);
    onError(message);
  }
  // Ownership prevents lowering a finger from stopping a manually started mic.
  function stop(source = 'button', cancel = false) {
    const current = capture;
    if (!current || current.source !== source) return;
    if (cancel || current.phase === 'requesting') {
      current.cancelled = true;
      current.controller.abort();
      if (current.recorder?.state === 'recording') current.recorder.stop();
      finish(current);
      status.textContent = 'Aufnahme abgebrochen.';
    } else if (current.phase === 'recording') {
      current.phase = 'uploading';
      refresh();
      current.recorder.stop();
    }
  }
  async function start(source = 'button') {
    if (!supported || !available || capture) return false;
    const current = { source, phase: 'requesting', cancelled: false, controller: new AbortController() };
    capture = current;
    setBusy(true);
    refresh();
    onStart?.();
    status.textContent = 'Mikrofonzugriff wird angefragt …';
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false });
      // Permission can arrive after release, disconnect, or a newer recording.
      if (current.cancelled || capture !== current) {
        stream.getTracks().forEach(track => track.stop());
        return false;
      }
      current.stream = stream;
      const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find(type => MediaRecorder.isTypeSupported(type));
      if (!mime) throw new Error('Dieser Browser unterstützt kein passendes Aufnahmeformat. Bitte Chrome oder Edge verwenden.');
      const recorder = new MediaRecorder(stream, { mimeType: mime, audioBitsPerSecond: 64000 });
      current.recorder = recorder;
      const chunks = [];
      let bytes = 0;
      recorder.ondataavailable = event => {
        if (current.cancelled) return;
        bytes += event.data.size;
        if (bytes <= 10 * 1024 * 1024) chunks.push(event.data);
        else fail(current, 'Aufnahme zu groß. Bitte kürzer sprechen.');
      };
      recorder.onerror = () => fail(current, 'Mikrofonaufnahme fehlgeschlagen. Bitte erneut versuchen.');
      stream.getAudioTracks().forEach(track => track.addEventListener('ended', () => {
        fail(current, 'Mikrofonverbindung unterbrochen. Bitte erneut versuchen.');
      }));
      recorder.onstop = async () => {
        release(current);
        if (current.cancelled || capture !== current) return;
        current.phase = 'uploading';
        refresh();
        status.textContent = 'Sprache wird erkannt …';
        const timeout = setTimeout(() => current.controller.abort(), 90000);
        try {
          if (!bytes || bytes > 10 * 1024 * 1024) throw new Error('Aufnahme leer oder zu groß.');
          const baseType = mime.split(';')[0];
          const form = new FormData();
          form.append('audio', new Blob(chunks, { type: baseType }), baseType === 'audio/mp4' ? 'speech.mp4' : 'speech.webm');
          const response = await fetch('/api/assistant/transcribe', { method: 'POST',
            headers: { 'X-Brain-Viewer': '1' }, body: form, signal: current.controller.signal });
          const data = await response.json();
          if (current.cancelled || capture !== current) return;
          if (!response.ok) throw new Error(data.error || 'Spracherkennung fehlgeschlagen.');
          finish(current);
          onText(data.text);
        } catch (error) {
          fail(current, error.name === 'AbortError' ? 'Zeitlimit der Spracherkennung erreicht.' : error.message);
        } finally { clearTimeout(timeout); }
      };
      recorder.start(1000);
      current.phase = 'recording';
      refresh();
      const started = Date.now();
      status.textContent = 'Aufnahme läuft · 0 / 60 s';
      current.timer = setInterval(() => {
        if (capture !== current || current.phase !== 'recording') return;
        const seconds = Math.floor((Date.now() - started) / 1000);
        status.textContent = `Aufnahme läuft · ${seconds} / 60 s`;
        if (seconds >= 60) stop(source);
      }, 250);
      return true;
    } catch (error) {
      fail(current, error.name === 'NotAllowedError' ? 'Mikrofonzugriff verweigert. Bitte in den Browser-Berechtigungen erlauben.' : error.name === 'NotFoundError' ? 'Kein Mikrofon gefunden.' : error.message);
      return false;
    }
  }
  if (!supported) button.title = unavailableReason;
  button.addEventListener('click', () => {
    if (capture?.phase === 'recording') stop(capture.source);
    else void start();
  });
  window.addEventListener('pagehide', () => { if (capture) stop(capture.source, true); });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stop('gesture', true);
  });
  refresh();
  return { start, stop, setAvailable(value) { available = value; refresh(); } };
}
