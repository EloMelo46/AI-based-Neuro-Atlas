// Keep original text positions until a complete group of sentences is available.
// Abbreviations, decimal numbers and ventricular ordinals are not sentence ends.
const abbreviation = /(?:\b(?:z|b|d|h|u|a|ca|bzw|usw|etc|dr|prof|mr|mrs|e|g)|\d+|\b[ivxlcdm]+)\.$/iu;

export function sentenceBatchEnd(text, final = false, count = 3, limit = 3000) {
  const ends = [];
  for (const match of text.matchAll(/[.!?]+["'»”’)]*(?=\s|$)/gu)) {
    const end = match.index + match[0].length;
    if (end === text.length && !final) continue; // A later delta may continue an abbreviation.
    if (text[match.index] === '.' && abbreviation.test(text.slice(0, match.index + 1))) continue;
    // Wait for complete links/citation markers before speaking their sentence.
    const prefix = text.slice(0, end);
    if ((prefix.match(/\[/g) || []).length !== (prefix.match(/\]/g) || []).length ||
        prefix.lastIndexOf('\uE200') > prefix.lastIndexOf('\uE201')) continue;
    ends.push(end);
    if (ends.length === count || end >= limit) break;
  }
  const within = ends.filter(end => end <= limit);
  if (within.length >= count) return within[count - 1];
  if (text.length >= limit) {
    if (within.length) return within.at(-1);
    // A pathological single sentence must still respect the speech input limit.
    const space = text.lastIndexOf(' ', limit);
    let end = space > 0 ? space : limit;
    if (/[\uD800-\uDBFF]/u.test(text[end - 1])) end--;
    return end;
  }
  return final ? text.length : 0;
}

export function createSentenceBatches(onBatch) {
  let text = '', consumed = 0, closed = false;
  function drain(final) {
    while (consumed < text.length) {
      const end = sentenceBatchEnd(text.slice(consumed), final);
      if (!end) break;
      const batch = text.slice(consumed, consumed + end);
      const start = consumed;
      consumed += end;
      if (batch.trim()) onBatch(batch, { start, end: consumed });
    }
  }
  return {
    push(delta) { if (!closed) { text += delta; drain(false); } },
    finish(finalText = text) {
      if (closed) return;
      closed = true;
      // Never replay already spoken text when a final server message replaces it.
      if (!finalText.startsWith(text.slice(0, consumed))) {
        throw new Error('Der Antworttext wurde nachträglich geändert. Bitte den restlichen Text im Chat lesen.');
      }
      text = finalText;
      drain(true);
    },
  };
}
