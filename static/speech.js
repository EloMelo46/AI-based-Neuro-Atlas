// One cancellable, low-latency playback queue. MP3 bytes are played as they arrive.
export function initSpeech({ onError = () => {} } = {}) {
  const audio = document.getElementById('assistant-audio');
  let generation = 0;
  let controller = null;
  let reader = null;
  let mediaSource = null;
  let blobURL = null;
  let releasePlayback = null;

  function stop() {
    generation++;
    controller?.abort();
    controller = null;
    void reader?.cancel().catch(() => {});
    reader = null;
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
    releasePlayback?.();
    releasePlayback = null;
    mediaSource = null;
    if (blobURL) URL.revokeObjectURL(blobURL);
    blobURL = null;
    audio.hidden = true;
  }

  function playbackFinished(current) {
    return new Promise((resolve, reject) => {
      const clear = () => {
        audio.onended = null;
        audio.onerror = null;
        releasePlayback = null;
      };
      releasePlayback = () => { clear(); resolve(); };
      audio.onended = () => { clear(); resolve(); };
      audio.onerror = () => {
        clear();
        reject(new Error('Audio konnte nicht abgespielt werden.'));
      };
      audio.play().catch(error => {
        if (current !== generation) resolve();
        else if (error.name === 'NotAllowedError') return;
        else { clear(); reject(error); }
      });
    });
  }

  async function append(source, bytes, current) {
    if (current !== generation) throw new DOMException('Abgebrochen', 'AbortError');
    await new Promise((resolve, reject) => {
      const clear = () => {
        source.removeEventListener('updateend', done);
        source.removeEventListener('error', failed);
      };
      const done = () => { clear(); resolve(); };
      const failed = () => { clear(); reject(new Error('Audiostream konnte nicht verarbeitet werden.')); };
      source.addEventListener('updateend', done, { once: true });
      source.addEventListener('error', failed, { once: true });
      source.appendBuffer(bytes);
    });
  }

  async function playResponse(response, current) {
    const canStream = response.body && window.MediaSource && MediaSource.isTypeSupported('audio/mpeg');
    if (!canStream) {
      const blob = await response.blob();
      if (current !== generation) return;
      blobURL = URL.createObjectURL(blob);
      audio.src = blobURL;
      audio.hidden = false;
      await playbackFinished(current);
      return;
    }

    mediaSource = new MediaSource();
    blobURL = URL.createObjectURL(mediaSource);
    audio.src = blobURL;
    audio.hidden = false;
    await new Promise((resolve, reject) => {
      mediaSource.addEventListener('sourceopen', resolve, { once: true });
      mediaSource.addEventListener('error', () => reject(new Error('Audiostream konnte nicht geöffnet werden.')), { once: true });
    });
    if (current !== generation) return;
    const source = mediaSource.addSourceBuffer('audio/mpeg');
    reader = response.body.getReader();
    let playback = null;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (value?.byteLength) {
        await append(source, value, current);
        if (!playback) {
          playback = playbackFinished(current);
        }
      }
    }
    reader = null;
    if (!playback) throw new Error('OpenAI hat keine Audiodaten geliefert.');
    if (mediaSource.readyState === 'open' && !source.updating) mediaSource.endOfStream();
    await playback;
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
    try {
      for (const chunk of chunks) {
        if (current !== generation) return;
        controller = new AbortController();
        const timeout = setTimeout(() => controller?.abort(), 75000);
        let response;
        try {
          response = await fetch('/api/assistant/speech', { method: 'POST', headers: {
            'Content-Type': 'application/json', 'X-Brain-Viewer': '1',
          }, body: JSON.stringify({ text: chunk, voice }), signal: controller.signal });
          if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || 'Sprachausgabe fehlgeschlagen.');
          }
          await playResponse(response, current);
        } finally { clearTimeout(timeout); }
      }
      if (current === generation) stop();
    } catch (error) {
      if (current !== generation) return;
      stop();
      onError(error.name === 'AbortError'
        ? 'Zeitlimit bei der Sprachausgabe. Die Textantwort bleibt verfügbar.'
        : error.message);
    }
  }

  document.getElementById('assistant-speak').addEventListener('change', stop);
  document.getElementById('assistant-voice').addEventListener('change', stop);
  window.addEventListener('pagehide', stop);
  return { speak, stop };
}
