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
  fullscreenButton.textContent = active ? 'Vollbild beenden' : 'Vollbild';
  fullscreenButton.setAttribute('aria-pressed', String(active));
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
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && matchMedia('(max-width: 900px)').matches) {
    selectPanel('scene');
    navigation.querySelector('button').focus();
  }
});
