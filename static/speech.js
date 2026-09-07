// One cancellable playback queue; late network responses never restart audio.
export function initSpeech() {
  const audio = document.getElementById('assistant-audio');
  const status = document.getElementById('speech-status');
  const stopButton = document.getElementById('speech-stop');
  let generation = 0;
  let controller = null;
  let blobURL = null;
  let releasePlayback = null;
  function stop() {
    generation++;
    controller?.abort();
    controller = null;
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
    releasePlayback?.();
    releasePlayback = null;
    if (blobURL) URL.revokeObjectURL(blobURL);
    blobURL = null;
    audio.hidden = true;
    stopButton.disabled = true;
    status.textContent = 'KI-generierte Stimme · OpenAI';
  }
  async function speak(parts, voice) {
    stop();
    const current = generation;
    // Strip source annotations before speaking, retaining the links in the chat.
    let text = parts.map(part => {
      const chars = Array.from(part.text);
      for (const cite of [...part.citations].sort((a, b) => b.start_index - a.start_index)) {
        if (Number.isInteger(cite.start_index) && Number.isInteger(cite.end_index) && cite.start_index >= 0 && cite.end_index <= chars.length) chars.splice(cite.start_index, cite.end_index - cite.start_index);
      }
      return chars.join('');
    }).join('\n').trim();
    const chunks = [];
    while (text.length) {
      let end = Math.min(1800, text.length);
      if (end < text.length) {
        const boundary = text.lastIndexOf(' ', end);
        if (boundary > 0) end = boundary;
      }
      chunks.push(text.slice(0, end));
      text = text.slice(end).trimStart();
    }
    stopButton.disabled = false;
    try {
      for (const chunk of chunks) {
        if (current !== generation) return;
        status.textContent = 'KI-Stimme wird erzeugt …';
        controller = new AbortController();
        const timeout = setTimeout(() => controller?.abort(), 75000);
        let response;
        let blob;
        try {
          response = await fetch('/api/assistant/speech', { method: 'POST', headers: {
            'Content-Type': 'application/json', 'X-Brain-Viewer': '1',
          }, body: JSON.stringify({ text: chunk, voice }), signal: controller.signal });
          if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || 'Sprachausgabe fehlgeschlagen.');
          }
          blob = await response.blob();
        } finally { clearTimeout(timeout); }
        if (current !== generation) return;
        if (blobURL) URL.revokeObjectURL(blobURL);
        blobURL = URL.createObjectURL(blob);
        audio.src = blobURL;
        audio.hidden = false;
        status.textContent = 'KI-generierte Stimme · Wiedergabe';
        await new Promise((resolve, reject) => {
          const clear = () => { audio.onended = null; audio.onerror = null; releasePlayback = null; };
          releasePlayback = () => { clear(); resolve(); };
          audio.onended = () => { clear(); resolve(); };
          audio.onerror = () => { clear(); reject(new Error('Audio konnte nicht abgespielt werden.')); };
          audio.play().catch(error => {
            if (current !== generation) { resolve(); }
            else if (error.name === 'NotAllowedError') status.textContent = 'Bitte im Audioplayer auf Play klicken.';
            else { clear(); reject(error); }
          });
        });
      }
      if (current === generation) stop();
    } catch (error) {
      if (current !== generation) return;
      stop();
      status.textContent = error.name === 'AbortError' ? 'Zeitlimit bei der Sprachausgabe. Textantwort bleibt verfügbar.' : error.message;
    }
  }
  stopButton.addEventListener('click', stop);
  document.getElementById('assistant-speak').addEventListener('change', stop);
  document.getElementById('assistant-voice').addEventListener('change', stop);
  window.addEventListener('pagehide', stop);
  return { speak, stop };
}
