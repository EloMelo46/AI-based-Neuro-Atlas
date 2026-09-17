// Positive values delay the glow only. This is a tunable starting point, not
// measured word alignment; use 0 to disable the correction.
export const DEFAULT_GLOW_OFFSET_SECONDS = 0.2;

// Estimate German speech timing from syllables and punctuation. Use the complete
// recording's duration when available, never the growing buffered stream length.
export function estimatedRegionMentions(segment, duration, offsetSeconds = DEFAULT_GLOW_OFFSET_SECONDS) {
  const spans = [];
  let total = 0.12; // Small initial speech lead-in.
  for (const token of segment.text.matchAll(/[\p{L}\p{N}]+(?:[-’'][\p{L}\p{N}]+)*|[.,;:!?…]+|\n+/gu)) {
    const word = token[0];
    spans.push({ start: token.index, end: token.index + word.length, time: total });
    if (/^[\p{L}\p{N}]/u.test(word)) {
      const syllables = Math.max(1, (word.match(/[aeiouyäöü]+/giu) || []).length);
      total += (0.09 + syllables * 0.16) / 1.1;
    } else {
      total += /[.!?…\n]/u.test(word) ? 0.35 : 0.16;
    }
  }
  total += 0.12;
  const length = Number.isFinite(duration) && duration > 0 ? duration : total;
  const offset = Number.isFinite(offsetSeconds) ? offsetSeconds : DEFAULT_GLOW_OFFSET_SECONDS;
  return segment.mentions.map(mention => {
    const position = mention.cueStart ?? mention.start;
    const span = spans.find(item => item.start <= position && position < item.end);
    const time = (span?.time ?? 0) / total * length;
    return {
      // Keep a late mention inside the recording so it can still trigger.
      at: Math.max(0, Math.min(Math.max(0, length - 0.08), time + offset)),
      regionIds: mention.regionIds,
    };
  });
}

// Observe the audio clock; never change its source, rate, volume or playback state.
export function followSpeechMentions(audio, timeline, { onCue }) {
  const getTimeline = typeof timeline === 'function' ? timeline : () => timeline;
  const seen = new Set();
  let timer = null;
  let playing = false;
  const events = [];
  function listen(name, fn) { audio.addEventListener(name, fn); events.push([name, fn]); }
  function halt() { playing = false; clearInterval(timer); timer = null; }
  function update() {
    if (!playing || audio.paused || audio.seeking || audio.ended || audio.readyState < 2) return;
    const position = audio.currentTime;
    const due = new Set();
    getTimeline().forEach((cue, index) => {
      if (seen.has(index) || cue.at > position) return;
      seen.add(index);
      // A forward seek must not replay old mentions in a burst.
      if (position - cue.at <= 1) cue.regionIds.forEach(id => due.add(id));
    });
    if (due.size) onCue([...due]);
  }
  function resume() {
    if (audio.paused || audio.seeking || audio.ended) return;
    playing = true;
    update();
    if (timer === null) timer = setInterval(update, 60);
  }
  if (getTimeline().length) {
    listen('playing', resume);
    listen('timeupdate', update);
    listen('pause', halt);
    listen('waiting', halt);
    listen('ended', halt);
    listen('seeking', () => { halt(); seen.clear(); });
    listen('seeked', resume);
  }
  return () => { halt(); events.forEach(([name, fn]) => audio.removeEventListener(name, fn)); };
}
