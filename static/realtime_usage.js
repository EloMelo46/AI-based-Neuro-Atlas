export function initRealtimeUsage() {
  const usage = document.getElementById('realtime-usage');
  const limitsElement = document.getElementById('realtime-limits');
  let totals, seen, limits, timer, active = false;
  const number = value => Number.isFinite(value) && value >= 0 ? value : 0;
  const format = value => value.toLocaleString('de-CH');
  const label = name => ({ tokens: 'Tokens', requests: 'Anfragen' }[name] || name);
  const secondsLeft = item => Math.max(0, Math.ceil((item.resetAt - Date.now()) / 1000));
  function render() {
    if (usage) usage.textContent = `${format(totals.input + totals.output)} Tokens gesamt · Eingabe ${format(totals.input)} · Ausgabe ${format(totals.output)} · davon Eingabe aus Cache ${format(totals.cached)} · ${seen.size} Antworten`;
    if (!limitsElement) return;
    limitsElement.replaceChildren();
    if (!limits.size) {
      limitsElement.textContent = active ? 'Warte auf Limitmeldung von OpenAI …' : 'Noch keine Limitdaten.';
    }
    for (const [name, item] of limits) {
      const row = document.createElement('p');
      const seconds = secondsLeft(item);
      row.textContent = `${label(name)}: ${format(item.remaining)} von ${format(item.limit)} verfügbar (zuletzt gemeldet). ` +
        (!active ? 'Sitzung beendet.' : seconds > 0 ? `Reset laut API in ca. ${seconds} s.` : 'Reset-Zeit erreicht; neue Limitmeldung abwarten.');
      row.className = 'hint';
      if (item.limit > 0 && item.remaining / item.limit < 0.1) row.classList.add('usage-low');
      limitsElement.appendChild(row);
    }
  }
  function reset() {
    clearInterval(timer);
    active = true;
    totals = { input: 0, output: 0, cached: 0 };
    seen = new Set();
    limits = new Map();
    render();
    timer = setInterval(render, 1000);
  }
  function stop() { active = false; clearInterval(timer); render(); }
  reset();
  stop();
  function describeLimits() {
    return [...limits].map(([name, item]) =>
      `${label(name)}: ${format(item.remaining)} von ${format(item.limit)}, Reset in ca. ${secondsLeft(item)} s`).join(' · ');
  }
  function retryDelayMs(preferred = 'tokens') {
    const entries = [...limits];
    if (!entries.length) return null;
    const exhausted = entries.filter(([, item]) => item.remaining <= 0);
    const candidates = exhausted.length ? exhausted : entries;
    const selected = candidates.find(([name]) => name === preferred) || candidates[0];
    return Math.max(250, selected[1].resetAt - Date.now() + 250);
  }
  return { reset, stop, describeLimits, retryDelayMs, handle(event) {
    if (event.type === 'rate_limits.updated') {
      for (const item of event.rate_limits || []) {
        if (typeof item.name !== 'string' || !Number.isFinite(item.limit) || !Number.isFinite(item.remaining)) continue;
        limits.set(item.name, {limit: number(item.limit), remaining: number(item.remaining), resetAt: Date.now() + number(item.reset_seconds) * 1000});
      }
      render();
    }
    if (event.type === 'response.done') {
      const response = event.response;
      if (!response?.id || !response.usage || seen.has(response.id)) return;
      seen.add(response.id);
      totals.input += number(response.usage.input_tokens);
      totals.output += number(response.usage.output_tokens);
      totals.cached += number(response.usage.input_token_details?.cached_tokens);
      render();
    }
  } };
}
