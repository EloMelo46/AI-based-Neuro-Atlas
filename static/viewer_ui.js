const navigation = document.querySelector('.mobile-nav');
function selectPanel(name) {
  document.body.dataset.panel = name;
  for (const button of navigation.querySelectorAll('button')) {
    button.setAttribute('aria-pressed', String(button.dataset.panel === name));
  }
  if (name === 'assistant') document.getElementById('assistant-panel').open = true;
}
navigation.addEventListener('click', event => {
  const button = event.target.closest('button[data-panel]');
  if (button) selectPanel(button.dataset.panel);
});
selectPanel('scene');
const fullscreenButton = document.getElementById('fullscreen-toggle');
const fullscreenStatus = document.getElementById('fullscreen-status');
function updateFullscreen() {
  const active = !!document.fullscreenElement;
  document.body.classList.toggle('viewer-fullscreen', active);
  fullscreenButton.textContent = 'Vollbild';
  fullscreenButton.setAttribute('aria-pressed', String(active));
  fullscreenButton.setAttribute('aria-label', active ? 'Vollbild beenden' : 'Vollbild starten');
  fullscreenButton.title = active ? 'Vollbild beenden (Esc)' : 'Vollbild starten';
}
fullscreenButton.addEventListener('click', async () => {
  fullscreenStatus.hidden = true;
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen();
    } else if (document.documentElement.requestFullscreen && document.fullscreenEnabled) {
      await document.documentElement.requestFullscreen();
    } else {
      throw new Error('Dieser Browser unterstützt kein Seiten-Vollbild. Auf dem Handy kannst du den Viewer gegebenenfalls zum Home-Bildschirm hinzufügen.');
    }
  } catch (error) {
    fullscreenStatus.textContent = error.message || 'Vollbild konnte nicht gestartet werden.';
    fullscreenStatus.hidden = false;
  }
  updateFullscreen();
});
document.addEventListener('fullscreenchange', updateFullscreen);
updateFullscreen();
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && document.fullscreenElement) {
    void document.exitFullscreen().catch(() => {});
    return;
  }
  if (event.key === 'Escape' && !document.fullscreenElement && !document.body.classList.contains('viewer-fullscreen') && matchMedia('(max-width: 900px)').matches) {
    selectPanel('scene');
    navigation.querySelector('button').focus();
  }
});

// Hide only the page cursor; physical mouse and gesture input remain enabled.
const CURSOR_IDLE_MS = 3000;
let cursorIdleTimer = null;
function showCursor() {
  window.clearTimeout(cursorIdleTimer);
  document.body.classList.remove('cursor-idle');
  if (!document.hidden) {
    cursorIdleTimer = window.setTimeout(() => document.body.classList.add('cursor-idle'), CURSOR_IDLE_MS);
  }
}
for (const type of ['pointermove', 'pointerdown']) {
  document.addEventListener(type, event => {
    if (event.pointerType !== 'touch') showCursor();
  }, { passive: true });
}
document.addEventListener('wheel', showCursor, { passive: true });
document.addEventListener('visibilitychange', showCursor);
window.addEventListener('focus', showCursor);
window.addEventListener('pagehide', () => window.clearTimeout(cursorIdleTimer));
showCursor();
