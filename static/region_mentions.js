// Explicit names only: this catalog drives temporary narration cues, never selection.
const paired = (...parts) => parts.flatMap(part => [`Left-${part}`, `Right-${part}`]);
const callosum = ['CC_Anterior', 'CC_Mid_Anterior', 'CC_Central', 'CC_Mid_Posterior', 'CC_Posterior'];
const forms = (stem, endings) => endings.map(ending => stem + ending);
const adjective = (stem, nouns) => forms(stem, ['e', 'en', 'er', 'em', 'es'])
  .flatMap(word => nouns.map(noun => `${word} ${noun}`));
const nucleus = stem => forms(stem + 'kern', ['', 's', 'es', 'e', 'en']);
const ventricle = (stem, number, roman, english, latin) => [
  ...adjective(stem, ['Ventrikel', 'Hirnventrikel']), `${stem}en Ventrikels`, `${stem}en Hirnventrikels`,
  ...[`${number}.`, `${roman}.`].flatMap(label => [`${label} Ventrikel`, `${label} Ventrikels`]),
  `Ventrikel ${number}`, `Ventrikel ${roman}`, `${english} ventricle`, `ventriculus ${latin}`,
];
// Explicit inflections keep word boundaries intact: no stemming or fuzzy name
// matching, which could confuse e.g. Thalamus with Hypothalamus.
// Additional terminology: NLM MeSH D002421 and FIPAT TNA systema ventriculare.
const aliases = [
  [paired('Thalamus'), ['Thalamus', 'Thalami']],
  [paired('Hippocampus'), ['Hippocampus', 'Hippokampus', 'Hippocampi', 'Hippokampi']],
  [paired('Amygdala'), ['Amygdala', 'Amygdalae', 'Amygdalen', 'Amygdalas', ...nucleus('Mandel')]],
  [paired('Cerebral-Cortex'), ['Großhirnrinde', 'Großhirnrinden', 'Hirnrinde', 'Hirnrinden', 'Großhirnkortex', 'Großhirncortex',
    'cerebral cortex', ...adjective('zerebral', ['Kortex', 'Cortex']), ...adjective('cerebral', ['Kortex', 'Cortex']),
    'Rinde des Großhirns', 'Kortex des Großhirns', 'Cortex des Großhirns']],
  [paired('Cerebral-White-Matter'), [...adjective('weiß', ['Substanz des Großhirns']),
    ...forms('Großhirnmark', ['', 's', 'es']), 'cerebral white matter']],
  [paired('Cerebral-Cortex', 'Cerebral-White-Matter'), [...forms('Großhirn', ['', 's', 'es']),
    ...forms('Cerebrum', ['', 's']), ...forms('Zerebrum', ['', 's'])]],
  [paired('Cerebellum-Cortex'), ['Kleinhirnrinde', 'Kleinhirnrinden', 'Kleinhirnkortex', 'cerebellar cortex',
    ...adjective('zerebellär', ['Kortex', 'Cortex']), ...adjective('cerebellär', ['Kortex', 'Cortex']),
    'Rinde des Kleinhirns', 'Kortex des Kleinhirns', 'Cortex des Kleinhirns']],
  [paired('Cerebellum-White-Matter'), [...adjective('weiß', ['Substanz des Kleinhirns']),
    ...forms('Kleinhirnmark', ['', 's', 'es']), 'cerebellar white matter']],
  [paired('Cerebellum-Cortex', 'Cerebellum-White-Matter'), [...forms('Kleinhirn', ['', 's', 'es']),
    ...forms('Cerebellum', ['', 's']), ...forms('Zerebellum', ['', 's'])]],
  [paired('Caudate'), ['Nucleus caudatus', 'Nuclei caudati', 'Caudatus', ...nucleus('Schweif'), 'caudate nucleus', 'caudate nuclei']],
  [paired('Putamen'), ['Putamen', 'Putamens', 'Putamina', ...nucleus('Schalen')]],
  [paired('Pallidum'), ['Pallidum', 'Pallidums', 'Globus pallidus']],
  [paired('Accumbens-area'), ['Nucleus accumbens', 'Nuclei accumbentes', 'Accumbens', ...nucleus('Accumbens-')]],
  [paired('Caudate', 'Putamen', 'Pallidum', 'Accumbens-area'), ['Basalganglien', 'Basalkerne', 'Basalkernen', 'basal ganglia', 'basal nuclei']],
  [paired('Caudate', 'Putamen', 'Accumbens-area'), ['Striatum', 'Striatums', 'Striata']],
  [['Brain-Stem'], [...forms('Hirnstamm', ['', 's', 'es']), ...forms('Gehirnstamm', ['', 's', 'es']), 'brain stem', 'brainstem']],
  [callosum, ['Corpus callosum', ...forms('Hirnbalken', ['', 's']), ...forms('Gehirnbalken', ['', 's']), 'Balken', 'Balkens']],
  [paired('Lateral-Ventricle'), [...forms('Seitenventrikel', ['', 'n', 's']), 'lateral ventricle', 'lateral ventricles',
    'ventriculus lateralis', 'ventriculi laterales']],
  [paired('Inf-Lat-Vent'), [...forms('Unterhorn', ['', 's', 'es']), 'Unterhörner', 'Unterhörnern',
    ...forms('Temporalhorn', ['', 's', 'es']), 'Temporalhörner', 'Temporalhörnern']],
  [['3rd-Ventricle'], ventricle('dritt', 3, 'III', 'third', 'tertius')],
  [['4th-Ventricle'], ventricle('viert', 4, 'IV', 'fourth', 'quartus')],
  [[...paired('Lateral-Ventricle', 'Inf-Lat-Vent'), '3rd-Ventricle', '4th-Ventricle'], [
    ...forms('Ventrikel', ['', 'n', 's']), ...forms('Hirnventrikel', ['', 'n', 's']), 'Ventrikelsystem', 'Ventrikelsystems']],
  [['CSF'], ['Liquor', 'Liquors', 'Gehirnflüssigkeit', 'Hirnflüssigkeit', 'Liquor cerebrospinalis', 'cerebrospinal fluid']],
  [paired('VentralDC'), [...adjective('ventral', ['Zwischenhirn', 'Zwischenhirns']), 'ventral diencephalon']],
  [['WM-hypointensities'], ['Hypointensitäten der weißen Substanz', 'Hypointensität der weißen Substanz', 'white matter hypointensities']],
];

function pattern(name) {
  return name.split(/(\s+|-)/u).map((part, index, parts) => {
    if (/^(?:\s+|-)$/u.test(part)) {
      // Allow ordinal forms with no space (3.Ventrikel) and typographic hyphens.
      return parts[index - 1]?.endsWith('.') ? '\\s*' : '[\\s\\-\u2010\u2011]+';
    }
    return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      .replace(/ß/g, '(?:ß|ss)').replace(/ä/g, '(?:ä|ae)').replace(/ö/g, '(?:ö|oe)').replace(/ü/g, '(?:ü|ue)');
  }).join('');
}

const wordBoundary = '[\\p{L}\\p{N}_\\-\u2010\u2011]';
const leftSide = '(?:link(?:e[nmrs]?|s(?:seitig(?:e[nmrs]?)?)?)|left)';
const rightSide = '(?:recht(?:e[nmrs]?|s(?:seitig(?:e[nmrs]?)?)?)|right)';
const sideWord = `(?:${leftSide}|${rightSide})`;
const bilateral = '(?:beide[nmrs]?|beidseits|beidseitig(?:e[nmrs]?)?|bilateral(?:e[nmrs]?)?)';
const sidePhrase = `(?:${sideWord}(?:\\s*(?:und|sowie|and|&|/)\\s*${sideWord})?|${bilateral})`;
const prefixSide = new RegExp(`(?<!${wordBoundary})(${sidePhrase})\\s+$`, 'iu');
const suffixSide = new RegExp(`^\\s+(?:(${sidePhrase})(?!${wordBoundary})|(?:der|in der|auf der)\\s+(${sidePhrase})\\s+(?:Hemisphäre|Hirnhälfte|Gehirnhälfte|Seite)(?!${wordBoundary})|\\((${sidePhrase})\\))`, 'iu');

function hemisphereFor(side) {
  const left = new RegExp(`(?<!${wordBoundary})${leftSide}(?!${wordBoundary})`, 'iu').test(side);
  const right = new RegExp(`(?<!${wordBoundary})${rightSide}(?!${wordBoundary})`, 'iu').test(side);
  return left === right ? null : left ? 'Left-' : 'Right-';
}

export function findRegionMentions(text, availableIds) {
  const available = new Set(availableIds);
  const entries = [...aliases, ...availableIds.map(id => [[id], [id]])];
  const matches = [];
  for (const [ids, names] of entries) {
    for (const name of names) {
      const regex = new RegExp(`(?<!${wordBoundary})${pattern(name)}(?!${wordBoundary})`, 'giu');
      for (const match of text.matchAll(regex)) {
        let start = match.index;
        let end = start + match[0].length;
        const before = text.slice(0, start);
        const after = text.slice(end);
        const prefix = before.match(prefixSide);
        const suffix = after.match(suffixSide);
        const hemisphere = hemisphereFor(prefix?.[1] || suffix?.slice(1).find(Boolean) || '');
        const regionIds = ids.filter(id => available.has(id) &&
          (!hemisphere || !/^(Left|Right)-/.test(id) || id.startsWith(hemisphere)));
        if (prefix) start -= prefix[0].length;
        if (suffix) end += suffix[0].length;
        matches.push({ start, end, cueStart: match.index, regionIds });
      }
    }
  }
  // Prefer the longest anatomical term over a nested generic name (e.g. Ventrikel).
  matches.sort((a, b) => (b.end - b.start) - (a.end - a.start));
  const accepted = [];
  for (const match of matches) {
    if (!accepted.some(other => match.start < other.end && match.end > other.start)) accepted.push(match);
  }
  // Resolve specificity before availability: an unavailable third ventricle
  // must not fall back to all available ventricles via the shorter generic name.
  return accepted.filter(match => match.regionIds.length).sort((a, b) => a.start - b.start);
}

export function narrationText(parts) {
  return parts.map(part => {
    const chars = Array.from(part.text);
    for (const cite of [...(part.citations || [])].sort((a, b) => b.start_index - a.start_index)) {
      if (Number.isInteger(cite.start_index) && Number.isInteger(cite.end_index) && cite.start_index >= 0 && cite.end_index >= cite.start_index && cite.end_index <= chars.length) {
        chars.splice(cite.start_index, cite.end_index - cite.start_index);
      }
    }
    return chars.join('');
  }).join('\n').replace(/\[([^\]]+)\]\(https?:\/\/[^)]+\)/g, '$1')
    .replace(/https?:\/\/\S+/g, '').replace(/\*\*|__|`/g, '').trim();
}

export function narrationSegments(parts, availableIds) {
  let rest = narrationText(parts);
  const segments = [];
  // Keep normal answers in one synthesis request. Split long answers only for
  // the API input limit, preferably at sentence boundaries, never for a glow cue.
  const limit = 3800;
  while (rest.length) {
    let end = Math.min(limit, rest.length);
    if (end < rest.length) {
      const sentences = [...rest.slice(0, end).matchAll(/[.!?]["»”)]*\s+|\n+/g)];
      const last = sentences.at(-1);
      const sentenceEnd = last ? last.index + last[0].length : 0;
      const space = rest.lastIndexOf(' ', end);
      end = sentenceEnd >= limit / 2 ? sentenceEnd : space > 0 ? space : end;
      // A hard limit must not divide a UTF-16 surrogate pair.
      if (/[\uD800-\uDBFF]/.test(rest[end - 1])) end--;
    }
    const text = rest.slice(0, end).trim();
    segments.push({ text, mentions: findRegionMentions(text, availableIds) });
    rest = rest.slice(end).trimStart();
  }
  return segments;
}

export function initMentionCues(viewer) {
  let timer = null;
  function stop() {
    clearTimeout(timer);
    timer = null;
    viewer.clearMentionGlow?.();
  }
  function showText(parts) {
    stop();
    const mentions = findRegionMentions(narrationText(parts), viewer.getState().loaded);
    let next = 0;
    const advance = () => {
      if (next >= mentions.length) return;
      viewer.glowRegions?.(mentions[next++].regionIds);
      timer = setTimeout(advance, 1000);
    };
    advance();
  }
  return { stop, showText, glow: ids => viewer.glowRegions?.(ids) };
}
