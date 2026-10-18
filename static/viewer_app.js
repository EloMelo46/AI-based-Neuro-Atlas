// MRI and meshes have separate renderers, data sources and entry points.
// Opening /mri never requests the model catalogue or any GLB file.
import { createMRIViewer } from './mri_viewer.js';
import { attachViewer } from './assistant_bridge.js';
import { attachGestureControl } from './gesture_control.js';

const select = document.getElementById('appearance');
const status = document.getElementById('status');
const groups = JSON.parse(document.getElementById('region-groups').textContent);
const mriRegions = JSON.parse(document.getElementById('mri-region-list').textContent);
export const mriViewer = createMRIViewer(mriRegions, groups);
let meshModule = null, meshLoading = null, modeVersion = 0;

function addRegionControls(meshes) {
  const list = document.getElementById('region-list');
  list.replaceChildren();
  meshes.forEach((region, index) => {
    if (region.selectable === false) return;
    const item = document.createElement('li');
    const label = document.createElement('label');
    label.className = 'region-row'; label.htmlFor = `region-${index}`; label.title = region.region_id;
    const checkbox = document.createElement('input');
    checkbox.id = label.htmlFor; checkbox.type = 'checkbox'; checkbox.disabled = true;
    checkbox.checked = region.default_visible !== false;
    const color = document.createElement('span');
    color.id = `region-color-${index}`; color.className = 'region-color'; color.setAttribute('aria-hidden', 'true');
    const name = document.createElement('span'); name.className = 'region-name'; name.textContent = region.name;
    const state = document.createElement('span'); state.id = `region-state-${index}`; state.className = 'region-state'; state.textContent = 'Lädt …';
    label.append(checkbox, color, name, state); item.append(label); list.append(item);
  });
}

async function loadMeshes() {
  if (meshModule) return meshModule;
  if (!meshLoading) meshLoading = (async () => {
    const data = document.getElementById('mesh-list');
    if (!JSON.parse(data.textContent).length) {
      const response = await fetch('/api/mesh-catalog');
      if (!response.ok) throw new Error('3D-Modelle fehlen oder konnten nicht geladen werden. Die MRT-Ansicht bleibt verfügbar.');
      const catalog = await response.json();
      data.textContent = JSON.stringify(catalog.meshes);
      addRegionControls(catalog.meshes);
    }
    meshModule = await import('./brain_viewer.js');
    return meshModule;
  })().catch(error => { meshLoading = null; throw error; });
  return meshLoading;
}

async function switchView(style) {
  const version = ++modeVersion;
  if (!['learning', 'natural', 'digital', 'mri'].includes(style)) throw new Error('Unbekannte Darstellung.');
  if (style === 'mri') {
    const selection = mriViewer.isActive() ? [] : meshModule?.assistantViewer.getState().highlighted ?? [];
    document.querySelector('#info h3').textContent = 'MRT · Originalaufnahmen';
    document.getElementById('reset').disabled = false;
    const state = await mriViewer.activate(selection);
    if (version !== modeVersion) throw new Error('Darstellungswechsel wurde ersetzt.');
    status.textContent = `${state.loaded.length} Regionen aus den Segmentierungsvolumen verfügbar`;
    history.replaceState(null, '', '/mri');
    return state;
  }
  status.textContent = '3D-Modelle werden geladen …';
  const module = await loadMeshes();
  if (version !== modeVersion) throw new Error('Darstellungswechsel wurde ersetzt.');
  mriViewer.deactivate();
  document.querySelector('#info h3').textContent = 'Gehirn – alle Regionen';
  const state = module.assistantViewer.execute({ name: 'set_appearance', arguments: { appearance: style } });
  status.textContent = `${state.loaded.length} auswählbare 3D-Regionen geladen`;
  history.replaceState(null, '', '/');
  return state;
}

export const assistantViewer = {
  getState() {
    if (mriViewer.isActive()) return mriViewer.getState();
    return meshModule?.assistantViewer.getState() ?? { appearance: 'learning', loaded: [], visible: [], highlighted: [], opacities: {}, cuts: { x: [0, 100], y: [0, 100], z: [0, 100] } };
  },
  execute(action) {
    if (action.name === 'set_appearance') return switchView(action.arguments.appearance);
    if (mriViewer.isActive()) return mriViewer.execute(action);
    if (!meshModule) throw new Error('3D-Modelle werden noch geladen.');
    return meshModule.assistantViewer.execute(action);
  },
  describe(action) {
    if (action.name === 'set_appearance') return `Darstellung: ${{ mri: 'MRT', learning: 'Lernen', natural: 'Natürlich', digital: 'Digital' }[action.arguments.appearance]}`;
    if (mriViewer.isActive()) {
      if (action.name === 'set_mri_scan') return `MRT-Aufnahme: ${action.arguments.scan === 'original' ? 'Original MRI' : 'Brain Only'}`;
      return { isolate_regions: 'Regionen im MRT markiert.', highlight_regions: 'MRT-Auswahl geändert.',
        reset_view: 'MRT-Ansicht zurückgesetzt.', set_visibility: 'Segmentierung geändert.' }[action.name] ?? 'MRT-Ansicht geändert.';
    }
    return meshModule?.assistantViewer.describe(action) ?? 'Ansicht wird geladen.';
  },
  glowRegions(ids) { if (!mriViewer.isActive()) meshModule?.assistantViewer.glowRegions(ids); },
  clearMentionGlow() { meshModule?.assistantViewer.clearMentionGlow(); },
  getMentionedRegions() { return mriViewer.isActive() ? [] : meshModule?.assistantViewer.getMentionedRegions() ?? []; },
};
attachViewer(assistantViewer);
attachGestureControl({ mriViewer, getMeshControls: () => meshModule?.gestureContext });
select.addEventListener('change', () => {
  void switchView(select.value).catch(error => { status.textContent = error.message; });
});
document.getElementById('reset').addEventListener('click', () => {
  if (mriViewer.isActive()) void mriViewer.execute({ name: 'reset_view', arguments: {} }).catch(error => { status.textContent = error.message; });
});

let initialStyle = document.body.dataset.initialViewer === 'mri' ? 'mri' : 'learning';
if (initialStyle !== 'mri') {
  try {
    const saved = localStorage.getItem('neuroatlas.appearance');
    if (['learning', 'natural', 'digital'].includes(saved)) initialStyle = saved;
  } catch { /* Storage is optional. */ }
}
await switchView(initialStyle);
