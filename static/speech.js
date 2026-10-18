import { narrationSegments } from './region_mentions.js';
import { createSentenceBatches } from './sentence_batches.js';
import { DEFAULT_GLOW_OFFSET_SECONDS, estimatedRegionMentions, followSpeechMentions } from './speech_timing.js';

// Stream sentence batches with independent visual cues and one block of lookahead.
export function initSpeech({ onError = () => {}, onCue = () => {}, onStop = () => {}, getRegionIds = () => [],
  glowOffsetSeconds = DEFAULT_GLOW_OFFSET_SECONDS } = {}) {
  const audio = document.getElementById('assistant-audio');
  const status = document.getElementById('assistant-speech-status');
  let generation = 0;
  let blobURL = null;
  const requests = new Set();
  const readers = new Set();
  let session = null;

  function release() {
    generation++;
    session?.resolve();
    session = null;
    for (const entry of requests) {
      clearTimeout(entry.timeout);
      entry.controller.abort();
    }
    requests.clear();
    for (const reader of readers) void reader.cancel().catch(() => {});
    readers.clear();
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
    if (blobURL) URL.revokeObjectURL(blobURL);
    blobURL = null;
    audio.hidden = true;
    if (status) status.hidden = true;
  }
  function stop() { release(); onStop(); }

  function waitFor(target, event, signal, start = () => {}) {
    return new Promise((resolve, reject) => {
      const clear = () => {
        target.removeEventListener(event, done);
        target.removeEventListener('error', failed);
        signal.removeEventListener('abort', aborted);
      };
      const done = () => { clear(); resolve(); };
      const failed = () => { clear(); reject(new Error('Audiostream konnte nicht verarbeitet werden.')); };
      const aborted = () => { clear(); reject(new DOMException('Abgebrochen', 'AbortError')); };
      if (signal.aborted) { aborted(); return; }
      target.addEventListener(event, done, { once: true });
      target.addEventListener('error', failed, { once: true });
      signal.addEventListener('abort', aborted, { once: true });
      try { start(); } catch (error) { clear(); reject(error); }
    });
  }

  function playbackFinished(entry, current) {
    const signal = entry.controller.signal;
    return new Promise((resolve, reject) => {
      const updateTiming = () => {
        if (entry.complete && Number.isFinite(audio.duration) && audio.duration > 0) {
          entry.timeline = estimatedRegionMentions(entry.segment, audio.duration, glowOffsetSeconds);
        }
      };
      audio.addEventListener('loadedmetadata', updateTiming);
      audio.addEventListener('durationchange', updateTiming);
      entry.updateTiming = updateTiming;
      updateTiming();
      const detachCues = followSpeechMentions(audio, () => entry.timeline, {
        onCue: ids => { if (current === generation) onCue(ids); },
      });
      const clear = () => {
        audio.removeEventListener('loadedmetadata', updateTiming);
        audio.removeEventListener('durationchange', updateTiming);
        entry.updateTiming = null;
        audio.removeEventListener('ended', done);
        audio.removeEventListener('error', failed);
        detachCues();
        signal.removeEventListener('abort', aborted);
      };
      const done = () => { clear(); resolve(); };
      const failed = () => { clear(); reject(new Error('Audio konnte nicht abgespielt werden.')); };
      const aborted = () => { clear(); reject(new DOMException('Abgebrochen', 'AbortError')); };
      if (signal.aborted) { aborted(); return; }
      audio.addEventListener('ended', done);
      audio.addEventListener('error', failed);
      signal.addEventListener('abort', aborted, { once: true });
      audio.play().catch(error => {
        if (current !== generation) return;
        // Keep listening for a real Play gesture; no premature glow on blocked autoplay.
        if (error.name !== 'NotAllowedError') { clear(); reject(error); }
      });
    });
  }

  async function playResponse(response, entry, current) {
    const signal = entry.controller.signal;
    if (blobURL) URL.revokeObjectURL(blobURL);
    const canStream = response.body && window.MediaSource && MediaSource.isTypeSupported('audio/mpeg');
    if (!canStream) {
      const blob = await response.blob();
      clearTimeout(entry.timeout);
      if (current !== generation) return;
      entry.complete = true;
      blobURL = URL.createObjectURL(blob);
      audio.src = blobURL;
      audio.hidden = false;
      await playbackFinished(entry, current);
      return;
    }
    const mediaSource = new MediaSource();
    blobURL = URL.createObjectURL(mediaSource);
    await waitFor(mediaSource, 'sourceopen', signal, () => {
      audio.src = blobURL;
      audio.hidden = false;
    });
    const source = mediaSource.addSourceBuffer('audio/mpeg');
    const reader = response.body.getReader();
    readers.add(reader);
    let playback = null;
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (signal.aborted || current !== generation) throw new DOMException('Abgebrochen', 'AbortError');
        if (done) break;
        if (value?.byteLength) {
          await waitFor(source, 'updateend', signal, () => source.appendBuffer(value));
          if (!playback) {
            playback = playbackFinished(entry, current);
            // Handle a playback error even if the download is still in progress.
            void playback.catch(() => { void reader.cancel().catch(() => {}); });
          }
        }
      }
      clearTimeout(entry.timeout);
      if (!playback) throw new Error('OpenAI hat keine Audiodaten geliefert.');
      if (mediaSource.readyState === 'open' && !source.updating) mediaSource.endOfStream();
      entry.complete = true;
      entry.updateTiming?.();
      await playback;
    } finally { readers.delete(reader); }
  }

  function prepare(segment, voice, buffer) {
    const entry = { controller: new AbortController(), timeout: null, ready: null, segment, complete: false,
      timeline: estimatedRegionMentions(segment, undefined, glowOffsetSeconds), updateTiming: null };
    requests.add(entry);
    entry.timeout = setTimeout(() => entry.controller.abort(), 75000);
    entry.ready = (async () => {
      try {
        let response = await fetch('/api/assistant/speech', { method: 'POST', headers: {
          'Content-Type': 'application/json', 'X-Brain-Viewer': '1',
        }, body: JSON.stringify({ text: segment.text, voice }), signal: entry.controller.signal });
        if (!response.ok) {
          const data = await response.json();
          throw new Error(data.error || 'Sprachausgabe fehlgeschlagen.');
        }
        if (buffer) {
          response = new Response(await response.blob());
          clearTimeout(entry.timeout);
        }
        return { response };
      } catch (error) {
        clearTimeout(entry.timeout);
        // A prefetched rejection must not become an unhandled promise rejection.
        return { error };
      }
    })();
    return entry;
  }

  function begin(voice) {
    stop();
    const current = generation;
    const queue = [];
    let running = false, finished = false, finalPart = null;
    const done = new Promise(resolve => { session = { resolve }; });
    function fail(error) {
      if (current !== generation) return;
      stop();
      onError(error.name === 'AbortError'
        ? 'Zeitlimit bei der Sprachausgabe. Die Textantwort bleibt verfügbar.' : error.message);
    }
    function prefetch() {
      // Bound network and memory usage to the current and next audio block.
      queue.slice(0, 2).forEach((item, index) => {
        if (!item.entry) item.entry = prepare(item.segment, voice, index > 0);
      });
    }
    async function pump() {
      if (running || current !== generation) return;
      running = true;
      try {
        while (queue.length && current === generation) {
          prefetch();
          const { entry } = queue[0];
          if (status) status.hidden = false;
          const { response, error } = await entry.ready;
          if (current !== generation) return;
          if (status) status.hidden = true;
          if (error) throw error;
          try { await playResponse(response, entry, current); }
          finally {
            clearTimeout(entry.timeout);
            entry.controller.abort();
            requests.delete(entry);
          }
          if (current !== generation) return;
          queue.shift();
        }
        if (finished && current === generation) release();
      } catch (error) { fail(error); }
      finally { running = false; }
    }
    const batches = createSentenceBatches((text, span) => {
      let citations = [];
      if (finalPart) {
        const start = Array.from(finalPart.text.slice(0, span.start)).length;
        const end = start + Array.from(text).length;
        citations = finalPart.citations.filter(c => c.start_index < end && c.end_index > start)
          .map(c => ({ ...c, start_index: Math.max(0, c.start_index - start), end_index: Math.min(end, c.end_index) - start }));
      }
      queue.push(...narrationSegments([{text, citations}], getRegionIds()).map(segment => ({ segment, entry: null })));
      prefetch();
      void pump();
    });
    return {
      push(delta) { if (current === generation) batches.push(delta); },
      finish(parts) {
        if (current !== generation) return done;
        let offset = 0;
        finalPart = { text: parts.map(p => p.text).join('\n'), citations: [] };
        for (const part of parts) {
          finalPart.citations.push(...(part.citations || []).map(c => ({...c,
            start_index: c.start_index + offset, end_index: c.end_index + offset })));
          offset += Array.from(part.text).length + 1;
        }
        try { batches.finish(finalPart.text); finished = true; void pump(); }
        catch (error) { fail(error); }
        return done;
      },
    };
  }

  function speak(parts, voice) { return begin(voice).finish(parts); }

  document.getElementById('assistant-speak').addEventListener('change', stop);
  document.getElementById('assistant-voice').addEventListener('change', stop);
  window.addEventListener('pagehide', stop);
  return { speak, begin, stop };
}
