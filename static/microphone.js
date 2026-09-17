export function initMicrophone({ button, status, setBusy, onText, onError, onStart }) {
  let available = false;
  let phase = 'idle';
  let recorder = null;
  let stream = null;
  let timer = null;
  let discarded = false;
  const supported = window.isSecureContext && navigator.mediaDevices?.getUserMedia && window.MediaRecorder;
  const hint = document.getElementById('assistant-mic-hint');
  const unavailableReason = !window.isSecureContext
    ? 'Mikrofon gesperrt: Öffne Neuro Atlas über HTTPS mit einem vertrauenswürdigen Zertifikat oder lokal über localhost. Der Textchat bleibt verfügbar.'
    : !supported
      ? 'Dieser Browser unterstützt keine Mikrofonaufnahme. Verwende einen aktuellen Browser. Der Textchat bleibt verfügbar.'
      : '';
  if (hint) {
    hint.textContent = unavailableReason;
    hint.hidden = !unavailableReason;
  }
  function refresh() {
    button.disabled = !supported || (phase === 'idle' ? !available : phase !== 'recording');
    button.textContent = phase === 'recording' ? 'Stoppen & senden' : 'Mikrofon starten';
    button.setAttribute('aria-pressed', String(phase === 'recording'));
  }
  function release() {
    clearInterval(timer);
    timer = null;
    stream?.getTracks().forEach(track => track.stop());
    stream = null;
  }
  if (!supported) button.title = unavailableReason;
  button.addEventListener('click', async () => {
    if (phase === 'recording') {
      phase = 'uploading';
      refresh();
      recorder.stop();
      return;
    }
    if (!available || phase !== 'idle') return;
    phase = 'requesting';
    discarded = false;
    setBusy(true);
    refresh();
    onStart?.();
    status.textContent = 'Mikrofonzugriff wird angefragt …';
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false });
      if (discarded) { release(); return; }
      const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find(type => MediaRecorder.isTypeSupported(type));
      if (!mime) throw new Error('Dieser Browser unterstützt kein passendes Aufnahmeformat. Bitte Chrome oder Edge verwenden.');
      recorder = new MediaRecorder(stream, { mimeType: mime, audioBitsPerSecond: 64000 });
      const chunks = [];
      let bytes = 0;
      recorder.ondataavailable = event => {
        bytes += event.data.size;
        if (bytes <= 10 * 1024 * 1024) chunks.push(event.data);
        else if (recorder.state === 'recording') recorder.stop();
      };
      recorder.onerror = () => {
        discarded = true;
        release();
        phase = 'idle';
        setBusy(false);
        refresh();
        onError('Mikrofonaufnahme fehlgeschlagen. Bitte erneut versuchen.');
      };
      recorder.onstop = async () => {
        release();
        if (discarded) return;
        phase = 'uploading';
        refresh();
        status.textContent = 'Sprache wird erkannt …';
        try {
          if (!bytes || bytes > 10 * 1024 * 1024) throw new Error('Aufnahme leer oder zu groß.');
          const baseType = mime.split(';')[0];
          const form = new FormData();
          form.append('audio', new Blob(chunks, { type: baseType }), baseType === 'audio/mp4' ? 'speech.mp4' : 'speech.webm');
          const response = await fetch('/api/assistant/transcribe', { method: 'POST',
            headers: { 'X-Brain-Viewer': '1' }, body: form, signal: AbortSignal.timeout(90000) });
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || 'Spracherkennung fehlgeschlagen.');
          phase = 'idle';
          setBusy(false);
          refresh();
          onText(data.text);
        } catch (error) {
          phase = 'idle';
          setBusy(false);
          refresh();
          onError(error.message);
        }
      };
      recorder.start(1000);
      phase = 'recording';
      refresh();
      const started = Date.now();
      status.textContent = 'Aufnahme läuft · 0 / 60 s';
      timer = setInterval(() => {
        const seconds = Math.floor((Date.now() - started) / 1000);
        status.textContent = `Aufnahme läuft · ${seconds} / 60 s`;
        if (seconds >= 60 && recorder.state === 'recording') { phase = 'uploading'; refresh(); recorder.stop(); }
      }, 250);
    } catch (error) {
      release();
      phase = 'idle';
      setBusy(false);
      refresh();
      onError(error.name === 'NotAllowedError' ? 'Mikrofonzugriff verweigert. Bitte in den Browser-Berechtigungen erlauben.' : error.name === 'NotFoundError' ? 'Kein Mikrofon gefunden.' : error.message);
    }
  });
  window.addEventListener('pagehide', () => {
    discarded = true;
    if (recorder?.state === 'recording') recorder.stop();
    release();
  });
  refresh();
  return { setAvailable(value) { available = value; refresh(); } };
}
