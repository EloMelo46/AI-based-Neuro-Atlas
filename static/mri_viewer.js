// NiiVue is loaded only when the MRI view is first opened. All data stays local.
import { scheduleMRIRendering } from './mri_render.js';

const MRI_GRAB_ROTATION_SENSITIVITY = 4.0;

export function createMRIViewer(regions, groups) {
  const palette = [[98, 214, 189], [233, 158, 113], [168, 146, 226], [126, 189, 242], [225, 122, 154], [201, 217, 126]];
  const byId = new Map(regions.filter(r => r.selectable !== false).map((r, index) => [r.region_id, { ...r, mriColor: palette[index % palette.length] }]));
  const host = document.getElementById('mri-scene');
  const status = document.getElementById('mri-status');
  const scanSelect = document.getElementById('mri-scan');
  const regionSelect = document.getElementById('mri-region');
  const clearButton = document.getElementById('mri-clear-selection');
  let active = false, main = null, rendering = null, library = null, catalog = null;
  let scan = 'brain', base = null, overlay = null;
  let selection = [], selectionData = null;
  let pending = Promise.resolve(), gestureTarget = null, gestureRender = false;
  let generation = 0;
  const run = task => {
    const job = pending.catch(() => {}).then(task);
    pending = job;
    return job;
  };
  function report(message, error = false) {
    status.textContent = message;
    status.dataset.error = String(error);
  }
  function safely(job) { void job.catch(error => report(error.message, true)); }
  async function json(url, body) {
    const response = await fetch(url, body ? {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Brain-Viewer': '1' },
      body: JSON.stringify(body),
    } : undefined);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'MRT-Daten konnten nicht geladen werden.');
    return result;
  }
  function populateRegions() {
    const supported = new Set(catalog.regions);
    const add = (value, name) => regionSelect.add(new Option(name, value));
    for (const group of groups) {
      if (group.region_ids.length && group.region_ids.every(id => supported.has(id))) add(group.group_id, group.name);
    }
    for (const [id, region] of byId) if (supported.has(id)) add(id, region.name);
  }
  async function newViewer(canvasId) {
    const nv = new library.Niivue({
      backColor: [0, 0, 0, 1], crosshairColor: [1, 0.3, 0.25, 1],
      multiplanarLayout: library.MULTIPLANAR_TYPE.GRID,
      multiplanarShowRender: library.SHOW_RENDER.ALWAYS, multiplanarEqualSize: true,
      isColorbar: false, show3Dcrosshair: true, isOrientCube: true,
      dragAndDropEnabled: false, forceDevicePixelRatio: 1, logLevel: 'error',
    });
    await nv.attachToCanvas(document.getElementById(canvasId));
    nv.setSliceType(library.SLICE_TYPE.MULTIPLANAR);
    return nv;
  }
  async function initialize() {
    if (main) return;
    catalog = await json('/api/mri/catalog');
    if (!catalog.scans.length) throw new Error('Keine MRT-Aufnahmen in original_mri/mri gefunden.');
    library = await import('./vendor/niivue/niivue.js');
    scanSelect.replaceChildren(...catalog.scans.map(item => new Option(item.name, item.id)));
    scan = catalog.scans[0].id;
    populateRegions();
    main = await newViewer('mri-main');
    rendering = scheduleMRIRendering(main, () => active);
  }
  async function loadScan(id) {
    if (!catalog.scans.some(item => item.id === id)) throw new Error('Diese MRT-Aufnahme ist nicht verfügbar.');
    if (base && id === scan) return;
    report('MRT-Aufnahme wird geladen …');
    const result = await json('/api/mri/scan/' + encodeURIComponent(id));
    const volume = await library.NVImage.loadFromUrl({ url: result.url, colormap: 'gray', trustCalMinMax: false });
    // Commit only after the complete image was decoded; a failed load preserves the old view.
    gestureEnd();
    main.volumes = [];
    main.addVolume(volume);
    main.scene.crosshairPos = [0.5, 0.5, 0.5];
    main.setRenderAzimuthElevation(120, 15);
    scan = id;
    base = volume;
    overlay = null;
    scanSelect.value = scan;
    document.getElementById('mri-scan-title').textContent = catalog.scans.find(s => s.id === id).name;
    if (selection.length) {
      try { await showSelection(selection); }
      catch (error) { clearSelection(); throw error; }
    }
    else report('Vier Ansichten bereit · Region links auswählen oder per Sprache zeigen lassen.');
  }
  function lookup(colors, names) {
    return { I: colors.map((_, i) => i), R: colors.map(c => c[0]), G: colors.map(c => c[1]),
      B: colors.map(c => c[2]), A: colors.map(c => c[3]), labels: names };
  }
  function updateOverlay(upload = true) {
    if (!overlay) return;
    const colors = [[0, 0, 0, 0]];
    for (const id of selectionData.region_ids) {
      const region = byId.get(id);
      const rgb = region.mriColor;
      colors.push([...rgb, 255]);
    }
    overlay.setColormapLabel(lookup(colors, ['', ...selectionData.names]));
    overlay.opacity = document.getElementById('mri-overlay').checked ? 1 : 0;
    if (upload) main.updateGLVolume();
  }
  async function showSelection(ids) {
    ids = [...new Set(ids)];
    if (!ids.length) { clearSelection(); return; }
    if (ids.some(id => !catalog.regions.includes(id))) throw new Error('Für eine gewählte Region fehlt die MRT-Segmentierung.');
    report('Regionen werden im Scan ausgerichtet …');
    const data = await json('/api/mri/selection', { scan, region_ids: ids });
    const labels = await library.NVImage.loadFromUrl({ url: data.labels_url, colormap: 'gray' });
    gestureEnd();
    main.volumes = [base];
    overlay = labels;
    selection = ids;
    selectionData = data;
    // Set discrete LUTs before uploading to the GPU (zero must stay transparent).
    updateOverlay(false);
    main.addVolume(labels);
    main.scene.crosshairPos = main.mm2frac(data.center_mm);
    clearButton.disabled = false;
    report('Markiert: ' + data.names.join(' · '));
    await rendering.flush();
  }
  function clearSelection() {
    selection = [];
    selectionData = null;
    gestureEnd();
    clearButton.disabled = true;
    if (main && base) { main.volumes = [base]; main.updateGLVolume(); }
    overlay = null;
    report('Vier Ansichten bereit · Region links auswählen oder per Sprache zeigen lassen.');
  }
  function getState() {
    const loaded = catalog?.regions ?? [];
    const visible = loaded.filter(id => !id.startsWith('csf.') || selection.includes(id));
    return { appearance: 'mri', ...(base ? { mri_scan: scan } : {}), loaded, visible, highlighted: [...selection],
      opacities: Object.fromEntries(loaded.map(id => [id, 1])),
      cuts: { x: [0, 100], y: [0, 100], z: [0, 100] } };
  }
  function gestureEnd() {
    gestureTarget = null;
    gestureRender = false;
    rendering?.setInteractive(false);
  }
  const api = {
    isActive: () => active,
    getState,
    getDiagnostics() {
      const view = nv => nv ? { tiles: nv.screenSlices.map(s => ({ type: s.axCorSag, rect: [...s.leftTopWidthHeight] })),
        azimuth: nv.scene.renderAzimuth, elevation: nv.scene.renderElevation,
        crosshair: [...nv.scene.crosshairPos], volumes: nv.volumes.length,
        pixelRatio: nv.uiData.dpr, canvasSize: [nv.canvas.width, nv.canvas.height] } : null;
      return { active, scan, main: view(main), interactivePreview: rendering?.isPreview() ?? false };
    },
    async activate(initialSelection = []) {
      const ticket = ++generation;
      active = true;
      host.hidden = false;
      document.getElementById('mri-region-controls').hidden = false;
      document.body.dataset.viewer = 'mri';
      document.body.dataset.appearance = 'mri';
      document.getElementById('appearance').value = 'mri';
      document.dispatchEvent(new Event('viewer-mode-change'));
      return run(async () => {
        try {
          await initialize();
          if (!base) await loadScan(scan);
          if (ticket !== generation) throw new Error('MRT-Wechsel wurde durch eine neuere Auswahl ersetzt.');
          if (initialSelection.length) await showSelection(initialSelection);
          main.resizeListener();
          await rendering.flush();
          return getState();
        } catch (error) { report(error.message, true); throw error; }
      });
    },
    deactivate() {
      generation++;
      active = false;
      gestureEnd();
      rendering?.cancel();
      host.hidden = true;
      document.getElementById('mri-region-controls').hidden = true;
      document.getElementById('gesture-pointer').hidden = true;
      document.body.dataset.viewer = 'mesh';
      document.dispatchEvent(new Event('viewer-mode-change'));
    },
    execute(action) {
      return run(async () => {
        if (!active || !base) throw new Error('MRT-Ansicht ist noch nicht bereit.');
        const ids = action.arguments.region_ids ?? [];
        if (!Array.isArray(ids) || ids.some(id => !catalog.regions.includes(id))) throw new Error('Unbekannte MRT-Region.');
        if (action.name === 'isolate_regions' && !ids.length) throw new Error('Keine Zielregion.');
        switch (action.name) {
          case 'set_mri_scan': await loadScan(action.arguments.scan); break;
          case 'isolate_regions':
          case 'highlight_regions': await showSelection(ids); break;
          case 'reset_view':
            clearSelection(); main.scene.crosshairPos = [0.5, 0.5, 0.5];
            main.scene.pan2Dxyzmm = [0, 0, 0, 1]; main.setScale(1);
            main.setRenderAzimuthElevation(120, 15); break;
          case 'set_visibility':
            if (typeof action.arguments.visible !== 'boolean') throw new Error('Ungültige Sichtbarkeit.');
            await showSelection(action.arguments.visible ? [...selection, ...ids] : selection.filter(id => !ids.includes(id)));
            break;
          case 'set_opacity': throw new Error('Die MRT-Deckkraft ist fest auf 100 % eingestellt.');
          case 'set_cut': throw new Error('MRT zeigt drei vollständige Schnittebenen. Das Schnittvolumen gehört zur 3D-Modellansicht; im MRT die Schnitte mit Klick oder Mausrad bewegen.');
          default: throw new Error('Unbekannte MRT-Aktion.');
        }
        await rendering.flush();
        return getState();
      }).catch(error => { report(error.message, true); throw error; });
    },
    gesturePoint(state) {
      const pointer = document.getElementById('gesture-pointer');
      const pos = state.pointer;
      pointer.hidden = !active || !state.connected || !pos || state.listening;
      if (pointer.hidden) return;
      const rect = document.getElementById('mri-viewers').getBoundingClientRect();
      pointer.style.left = `${rect.left + pos[0] * rect.width}px`;
      pointer.style.top = `${rect.top + pos[1] * rect.height}px`;
      pointer.classList.toggle('grabbing', state.holding);
    },
    gestureStart(state) {
      gestureEnd();
      if (!state.pointer || !active) return;
      const area = document.getElementById('mri-viewers').getBoundingClientRect();
      const x = area.left + state.pointer[0] * area.width, y = area.top + state.pointer[1] * area.height;
      const nv = main;
      if (nv) {
        const rect = nv.canvas.getBoundingClientRect();
        if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) return;
        gestureTarget = nv;
        gestureRender = nv.inRenderTile((x - rect.left) * nv.uiData.dpr, (y - rect.top) * nv.uiData.dpr) >= 0;
        rendering.setInteractive(gestureRender);
        if (!gestureRender) nv.mouseClick(x - rect.left, y - rect.top);
      }
    },
    gestureMove(dx, dy, state) {
      if (!active || !gestureTarget) return;
      if (gestureRender) gestureTarget.setRenderAzimuthElevation(
        gestureTarget.scene.renderAzimuth + dx * 360 * MRI_GRAB_ROTATION_SENSITIVITY,
        gestureTarget.scene.renderElevation + dy * 360 * MRI_GRAB_ROTATION_SENSITIVITY);
      else if (state.pointer) {
        const area = document.getElementById('mri-viewers').getBoundingClientRect();
        const rect = gestureTarget.canvas.getBoundingClientRect();
        const x = area.left + state.pointer[0] * area.width - rect.left;
        const y = area.top + state.pointer[1] * area.height - rect.top;
        if (x >= 0 && y >= 0 && x <= rect.width && y <= rect.height) gestureTarget.mouseClick(x, y);
      }
    },
    gestureEnd,
  };
  document.getElementById('mri-show-region').addEventListener('click', () => {
    const value = regionSelect.value;
    if (!value) return;
    const ids = groups.find(g => g.group_id === value)?.region_ids ?? [value];
    safely(api.execute({ name: 'isolate_regions', arguments: { region_ids: ids } }));
  });
  scanSelect.addEventListener('change', () => {
    const id = scanSelect.value;
    safely(api.execute({ name: 'set_mri_scan', arguments: { scan: id } })
      .finally(() => { scanSelect.value = scan; }));
  });
  clearButton.addEventListener('click', () => safely(run(clearSelection)));
  document.getElementById('mri-reset').addEventListener('click', () => safely(api.execute({ name: 'reset_view', arguments: {} })));
  document.getElementById('mri-overlay').addEventListener('change', () => updateOverlay());
  return api;
}
