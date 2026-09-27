import * as THREE from 'three';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createCutCaps } from './cut_caps.js';
import { createMentionGlow } from './mention_glow.js';
import { createBrainAppearance } from './brain_appearance.js';
import { attachGestureControl } from './gesture_control.js';
import { attachViewer } from './assistant_bridge.js';

// FreeSurfer triangle surfaces: two header lines, big-endian float32
// coordinates and zero-based int32 triangle indices (regardless of extension).
export function parseSurface(buffer) {
  const bytes = new Uint8Array(buffer);
  if (bytes[0] !== 255 || bytes[1] !== 255 || bytes[2] !== 254) {
    return new OBJLoader().parse(new TextDecoder().decode(buffer));
  }
  const view = new DataView(buffer);
  let offset = 3;
  for (let line = 0; line < 2; line++) {
    while (offset < bytes.length && bytes[offset] !== 10) offset++;
    offset++;
  }
  if (offset + 8 > bytes.length) throw new Error('FreeSurfer-Header ist unvollständig.');
  const vertexCount = view.getInt32(offset);
  const faceCount = view.getInt32(offset + 4);
  offset += 8;
  if (vertexCount <= 0 || faceCount <= 0 || offset + 12 * (vertexCount + faceCount) > bytes.length) {
    throw new Error('FreeSurfer-Geometriedaten fehlen oder sind unvollständig.');
  }
  const positions = new Float32Array(vertexCount * 3);
  for (let i = 0; i < positions.length; i++, offset += 4) {
    positions[i] = view.getFloat32(offset);
    if (!Number.isFinite(positions[i])) throw new Error('Ungültige Koordinate.');
  }
  const indices = new Uint32Array(faceCount * 3);
  for (let i = 0; i < indices.length; i++, offset += 4) {
    const index = view.getInt32(offset);
    if (index < 0 || index >= vertexCount) throw new Error('Ungültiger Dreiecksindex.');
    indices[i] = index;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setIndex(new THREE.BufferAttribute(indices, 1));
  geometry.computeVertexNormals();
  return new THREE.Mesh(geometry);
}

const status = document.getElementById('status');
const errors = document.getElementById('errors');
const names = JSON.parse(document.getElementById('mesh-list').textContent);
const scene = new THREE.Scene();
// Transparent canvas lets each appearance use a subtle CSS backdrop.
const brain = new THREE.Group();
// FreeSurfer RAS: Z points superior; Three.js: Y points up.
brain.rotation.x = -Math.PI / 2;
scene.add(brain);
const sceneHost = document.getElementById('scene');
const camera = new THREE.PerspectiveCamera(45, sceneHost.clientWidth / sceneHost.clientHeight, 0.1, 2000);
const renderer = new THREE.WebGLRenderer({ antialias: true, stencil: true, alpha: true });
renderer.localClippingEnabled = true;
renderer.setPixelRatio(1);
renderer.setSize(sceneHost.clientWidth, sceneHost.clientHeight);
sceneHost.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
const rotationToggle = document.getElementById('auto-rotate');
let resumeRotationAfterCuts = false;
let interacting = false;
let lastFrameTime = null;
const rotationOffset = new THREE.Vector3();
controls.addEventListener('start', () => { interacting = true; });
controls.addEventListener('end', () => { interacting = false; lastFrameTime = null; requestRender(); });
rotationToggle.addEventListener('change', () => {
  // A manual choice supersedes a rotation pause made for a cut view.
  resumeRotationAfterCuts = false;
  lastFrameTime = null;
  requestRender();
});
document.addEventListener('visibilitychange', () => {
  lastFrameTime = null;
  if (!document.hidden) requestRender();
});
let framePending = false;
let caps = null;
let mentionGlow = null;
function requestRender() {
  if (framePending) return;
  framePending = true;
  requestAnimationFrame(time => {
    framePending = false;
    if (document.hidden) { lastFrameTime = null; return; }
    const delta = lastFrameTime === null ? 0 : Math.min((time - lastFrameTime) / 1000, 0.1);
    lastFrameTime = time;
    const rotating = rotationToggle.checked && !interacting;
    if (rotating) {
      // Orbit the current focus without changing anatomical axes or cut planes.
      rotationOffset.copy(camera.position).sub(controls.target).applyAxisAngle(camera.up, -delta * 0.06);
      camera.position.copy(controls.target).add(rotationOffset);
    }
    controls.update();
    caps?.update(document.getElementById('fill-cuts').checked);
    const glowing = mentionGlow?.update(time);
    renderer.render(scene, camera);
    if (rotating || glowing) requestRender();
  });
}
controls.addEventListener('change', requestRender);
const meshDetail = document.getElementById('mesh-detail');
meshDetail.addEventListener('change', () => {
  meshDetail.disabled = true;
  status.textContent = 'Mesh-Details werden neu geladen …';
  const url = new URL(window.location.href);
  url.searchParams.set('detail', meshDetail.value);
  window.location.assign(url);
});
function updateResolution() {
  const value = document.getElementById('resolution').value;
  renderer.setPixelRatio(value === 'native' ? window.devicePixelRatio || 1 : Number(value));
}
document.getElementById('resolution').addEventListener('change', () => {
  updateResolution();
  requestRender();
});
document.getElementById('fill-cuts').addEventListener('change', requestRender);
let loaded = 0;
let failed = 0;

// Keep sorted file order and retain the original learning color for every region.
const regions = names.map((name, index) => {
  const color = new THREE.Color().setHSL((index * 0.61803398875) % 1, 0.65, 0.6);
  const checkbox = document.getElementById(`region-${index}`);
  const state = document.getElementById(`region-state-${index}`);
  const swatch = document.getElementById(`region-color-${index}`);
  const region = { id: name.slice(0, -4), color, checkbox, state, swatch, object: null, optIn: name === 'CSF.obj' };
  checkbox.addEventListener('change', () => {
    if (region.object) region.object.visible = checkbox.checked;
    updateRegionCount();
  });
  return region;
});
const appearance = createBrainAppearance(THREE, scene, regions, requestRender, () => {
  // Only automatic context follows the style. Explicit opacity edits survive.
  for (const region of regions) {
    if (region.object && region.focusContext) {
      setRegionOpacity(region, appearance.getContextOpacity(), false, true);
    }
  }
});

function updateRegionCount() {
  requestRender();
  const available = regions.filter(region => region.object);
  const visible = available.filter(region => region.object.visible).length;
  document.getElementById('region-count').textContent =
    `${visible} von ${available.length} geladenen Arealen eingeblendet`;
}

function setAllRegions(visible) {
  regions.forEach(region => {
    // Remember the choice for surfaces whose download is still in progress.
    if (!region.object && region.state.dataset.failed) return;
    const nextVisibility = visible && !region.optIn;
    region.checkbox.checked = nextVisibility;
    if (region.object) region.object.visible = nextVisibility;
  });
  updateRegionCount();
}
document.getElementById('show-regions').addEventListener('click', () => setAllRegions(true));
document.getElementById('hide-regions').addEventListener('click', () => setAllRegions(false));
document.getElementById('show-regions').disabled = names.length === 0;
document.getElementById('hide-regions').disabled = names.length === 0;
updateRegionCount();

// Define cuts in the original anatomical axes, then transform their planes
// with the brain's RAS-to-view rotation. Camera movement does not affect cuts.
const cutAxes = ['x', 'y', 'z'];
const cutBounds = new THREE.Box3();
const cutPlanes = cutAxes.flatMap(() => [
  new THREE.Plane(new THREE.Vector3(1, 0, 0), 1e10),
  new THREE.Plane(new THREE.Vector3(-1, 0, 0), 1e10),
]);
const cutInputs = cutAxes.map(axis => ({
  min: document.getElementById(`${axis}-min`),
  max: document.getElementById(`${axis}-max`),
}));

function updateCuts() {
  if (cutBounds.isEmpty()) return;
  const hasCuts = cutInputs.some(inputs => Number(inputs.min.value) > 0 || Number(inputs.max.value) < 100);
  appearance.setCutsActive(hasCuts);
  if (!hasCuts && resumeRotationAfterCuts) {
    rotationToggle.checked = true;
    resumeRotationAfterCuts = false;
    lastFrameTime = null;
  }
  requestRender();
  brain.updateMatrixWorld(true);
  cutAxes.forEach((axis, index) => {
    const range = cutBounds.max[axis] - cutBounds.min[axis];
    const lower = Number(cutInputs[index].min.value);
    const upper = Number(cutInputs[index].max.value);
    // Small padding at the endpoints keeps the complete surface visible.
    const padding = Math.max(range * 0.00001, 0.00001);
    const start = cutBounds.min[axis] + range * lower / 100 - (lower === 0 ? padding : 0);
    const end = cutBounds.min[axis] + range * upper / 100 + (upper === 100 ? padding : 0);
    const normal = new THREE.Vector3();
    normal[axis] = 1;
    cutPlanes[index * 2].set(normal, -start).applyMatrix4(brain.matrixWorld);
    cutPlanes[index * 2 + 1].set(normal.negate(), end).applyMatrix4(brain.matrixWorld);
    for (const bound of ['min', 'max']) {
      document.getElementById(`${axis}-${bound}-value`).value = `${cutInputs[index][bound].value} %`;
    }
  });
}

cutInputs.forEach((inputs, index) => {
  for (const bound of ['min', 'max']) {
    inputs[bound].addEventListener('input', () => {
      // Move the opposite endpoint along if the handles cross.
      if (Number(inputs.min.value) > Number(inputs.max.value)) {
        inputs[bound === 'min' ? 'max' : 'min'].value = inputs[bound].value;
      }
      updateCuts();
      faceCut(cutAxes[index], bound);
    });
  }
});
document.getElementById('reset-cuts').addEventListener('click', () => {
  cutInputs.forEach(inputs => {
    inputs.min.value = 0;
    inputs.max.value = 100;
  });
  updateCuts();
});

function initializeCuts() {
  if (!loaded) return;
  brain.updateMatrixWorld(true);
  cutBounds.setFromObject(brain).applyMatrix4(brain.matrixWorld.clone().invert());
  appearance.setBounds(cutBounds);
  updateCuts();
  cutAxes.forEach(axis => { document.getElementById(`cut-${axis}`).disabled = false; });
  document.getElementById('reset-cuts').disabled = false;
}

// RAS anterior (+Y) becomes world -Z after the brain rotation: look from front-right.
function fitCamera(targetBounds = null, direction = new THREE.Vector3(0.5, 0.3, -1), margin = 0.6) {
  const bounds = targetBounds instanceof THREE.Box3 ? targetBounds : new THREE.Box3().setFromObject(brain);
  if (bounds.isEmpty()) return;
  const sphere = bounds.getBoundingSphere(new THREE.Sphere());
  const vertical = THREE.MathUtils.degToRad(camera.fov) / 2;
  const horizontal = Math.atan(Math.tan(vertical) * camera.aspect);
  const radius = Math.max(sphere.radius, 0.01);
  // Cut views use a full bounding-sphere fit; the default view retains its zoom.
  const distance = radius / Math.sin(Math.min(vertical, horizontal)) * margin;
  // Consume any pending drag/pan damping before applying an explicit camera view.
  const damping = controls.enableDamping;
  controls.enableDamping = false;
  controls.update();
  controls.target.copy(sphere.center);
  camera.position.copy(sphere.center).add(direction.clone().normalize().multiplyScalar(distance));
  const offset = radius * 0.05;
  camera.position.y -= offset;
  controls.target.y -= offset;
  camera.near = radius / 1000;
  camera.far = distance + radius * 100;
  camera.updateProjectionMatrix();
  controls.minDistance = radius * 0.2;
  controls.maxDistance = Math.max(radius * 5, distance * 2);
  controls.update();
  controls.enableDamping = damping;
  requestRender();
}

function faceCut(axis, preferredBound = null) {
  const index = cutAxes.indexOf(axis);
  if (index < 0 || cutBounds.isEmpty()) return;
  const lower = Number(cutInputs[index].min.value);
  const upper = Number(cutInputs[index].max.value);
  if (lower === 0 && upper === 100) return; // Removing a cut does not move the camera.
  brain.updateMatrixWorld(true);
  const normal = new THREE.Vector3();
  normal[axis] = 1;
  normal.transformDirection(brain.matrixWorld);
  // Look from the removed side. For a slab, prefer the edited face (sliders)
  // or whichever face is nearer the current viewing direction (assistant).
  let bound = lower === 0 ? 'max' : upper === 100 ? 'min' : preferredBound;
  if (!bound) {
    bound = camera.position.clone().sub(controls.target).dot(normal) >= 0 ? 'max' : 'min';
  }
  if (bound === 'min') normal.negate();
  const faceBounds = cutBounds.clone();
  cutAxes.forEach((name, i) => {
    const range = cutBounds.max[name] - cutBounds.min[name];
    faceBounds.min[name] = cutBounds.min[name] + range * Number(cutInputs[i].min.value) / 100;
    faceBounds.max[name] = cutBounds.min[name] + range * Number(cutInputs[i].max.value) / 100;
  });
  faceBounds.min[axis] = faceBounds.max[axis] = faceBounds[bound][axis];
  faceBounds.applyMatrix4(brain.matrixWorld);
  resumeRotationAfterCuts ||= rotationToggle.checked;
  rotationToggle.checked = false;
  lastFrameTime = null;
  fitCamera(faceBounds, normal, 1.02);
}

function updateStatus() {
  status.textContent = `${loaded} von ${names.length} Regionen geladen` +
    (failed ? ` · ${failed} fehlgeschlagen` : '') +
    (loaded + failed < names.length ? ' …' : '');
}

async function loadRegion(name, index) {
  try {
    const response = await fetch('/mesh/' + encodeURIComponent(name) + '?detail=' + encodeURIComponent(meshDetail.value));
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const object = parseSurface(await response.arrayBuffer());
    let triangles = 0;
    object.traverse(child => {
      if (!child.isMesh) return;
      triangles += (child.geometry.index?.count ?? child.geometry.attributes.position?.count ?? 0) / 3;
      const oldMaterials = Array.isArray(child.material) ? child.material : [child.material];
      oldMaterials.forEach(material => material.dispose());
      child.material = appearance.createMaterial(regions[index], cutPlanes, child.geometry);
    });
    if (!triangles) throw new Error('Datei enthält keine Dreiecksflächen.');
    object.name = name;
    object.visible = regions[index].checkbox.checked;
    brain.add(object);
    regions[index].object = object;
    regions[index].checkbox.disabled = false;
    regions[index].state.textContent = '';
    loaded++;
    if (loaded === 1) fitCamera();
  } catch (error) {
    failed++;
    regions[index].checkbox.checked = false;
    regions[index].checkbox.disabled = true;
    regions[index].state.textContent = 'Fehler';
    regions[index].state.dataset.failed = 'true';
    const item = document.createElement('li');
    item.textContent = `${name}: ${error.message}`;
    errors.appendChild(item);
    console.error(name, error);
  }
  updateStatus();
  updateRegionCount();
}

document.getElementById('reset').addEventListener('click', fitCamera);
new ResizeObserver(() => {
  const aspect = sceneHost.clientWidth / Math.max(1, sceneHost.clientHeight);
  // Preserve the zoom relative to the smaller viewport dimension when a panel opens.
  const halfFov = THREE.MathUtils.degToRad(camera.fov) / 2;
  const oldAngle = Math.atan(Math.tan(halfFov) * Math.min(1, camera.aspect));
  const newAngle = Math.atan(Math.tan(halfFov) * Math.min(1, aspect));
  if (newAngle > 0) camera.position.sub(controls.target).multiplyScalar(Math.sin(oldAngle) / Math.sin(newAngle)).add(controls.target);
  camera.aspect = aspect;
  camera.updateProjectionMatrix();
  updateResolution();
  renderer.setSize(sceneHost.clientWidth, Math.max(1, sceneHost.clientHeight));
  requestRender();
}).observe(sceneHost);
renderer.domElement.addEventListener('webglcontextlost', event => {
  event.preventDefault();
  status.textContent = 'WebGL-Verbindung verloren. Bitte Seite neu laden.';
});

updateStatus();
// Limit concurrent downloads and parsing of large surfaces.
let next = 0;
await Promise.all(Array.from({ length: Math.min(4, names.length) }, async () => {
  while (next < names.length) {
    const index = next++;
    await loadRegion(names[index], index);
  }
}));
fitCamera();
initializeCuts();
caps = createCutCaps(THREE, scene, brain, cutPlanes);
requestRender();
document.getElementById('reset').disabled = loaded === 0;
if (!names.length) status.textContent = 'Keine .obj-Dateien in export_preview gefunden.';

const regionMap = new Map(regions.map((region, index) => [names[index].slice(0, -4), region]));
mentionGlow = createMentionGlow(THREE, scene, regionMap, cutPlanes, requestRender, appearance.getStyle);

function setRegionOpacity(region, opacity, makeVisible = true, focusContext = false) {
  region.opacity = opacity;
  region.focusContext = focusContext;
  if (makeVisible) {
    region.object.visible = true;
    region.checkbox.checked = true;
  }
  region.object.traverse(child => {
    if (!child.isMesh) return;
    child.material.opacity = opacity;
  });
  appearance.applyRegion(region);
  region.state.textContent = opacity < 1 ? `${Math.round(opacity * 100)} % deckend` : '';
}

function selectRegions(selected) {
  for (const region of regions) {
    if (!region.object) continue;
    region.highlighted = selected.includes(region);
    if (!selected.length) region.focusContext = false;
    appearance.applyRegion(region);
  }
}

export const assistantViewer = {
  glowRegions(ids) { mentionGlow.glow(ids); },
  clearMentionGlow() { mentionGlow.clear(); },
  getMentionedRegions() { return mentionGlow.getActiveIds(); },
  getState() {
    const matching = predicate => [...regionMap].filter(([, region]) => region.object && predicate(region)).map(([id]) => id);
    return {
      appearance: appearance.getStyle(),
      loaded: matching(() => true), visible: matching(region => region.object.visible),
      highlighted: matching(region => region.highlighted),
      opacities: Object.fromEntries([...regionMap].filter(([, region]) => region.object).map(([id, region]) => [id, region.opacity ?? 1])),
      cuts: Object.fromEntries(cutAxes.map((axis, index) => [axis, [Number(cutInputs[index].min.value), Number(cutInputs[index].max.value)]])),
    };
  },
  execute(action) {
    const args = action.arguments;
    const allowed = ['highlight_regions', 'set_visibility', 'set_opacity', 'isolate_regions', 'set_cut', 'set_appearance', 'reset_view'];
    if (!allowed.includes(action.name) || !args || typeof args !== 'object') throw new Error('Unbekannte Vieweraktion.');
    const selected = (args.region_ids ?? []).map(id => {
      const region = regionMap.get(id);
      if (!region?.object) throw new Error(`Areal nicht geladen: ${id}`);
      return region;
    });
    const focusing = action.name === 'isolate_regions' || (action.name === 'highlight_regions' && selected.length > 0);
    if (action.name === 'highlight_regions' && !selected.length) {
      // Compatibility for clearing a selection; not offered as an AI tool.
      selectRegions(selected);
    } else if (action.name === 'set_opacity') {
      if (!selected.length || !Number.isFinite(args.opacity) || args.opacity < 0 || args.opacity > 1) throw new Error('Deckkraft muss zwischen 0 und 1 liegen; mindestens ein Areal wählen.');
      for (const region of selected) setRegionOpacity(region, args.opacity);
    } else if (action.name === 'set_visibility') {
      if (typeof args.visible !== 'boolean') throw new Error('Ungültige Sichtbarkeit.');
      for (const region of regions) {
        if (!region.object) continue;
        if (selected.includes(region)) {
          region.object.visible = args.visible;
          region.checkbox.checked = region.object.visible;
        }
      }
    } else if (focusing) {
      if (!selected.length) throw new Error('Keine Zielregion.');
      selectRegions(selected);
      for (const region of regions) {
        if (!region.object) continue;
        if (region.optIn && !selected.includes(region)) {
          setRegionOpacity(region, 1, false);
          region.object.visible = false;
          region.checkbox.checked = false;
        } else {
          const target = selected.includes(region);
          setRegionOpacity(region, target ? 1 : appearance.getContextOpacity(), true, !target);
        }
      }
      // Old cuts must not keep the newly requested anatomy out of view.
      document.getElementById('reset-cuts').click();
      // Preserve the camera, zoom and pan; clearing cuts resumes their paused rotation.
    } else if (action.name === 'set_appearance') {
      if (!['learning', 'natural', 'digital'].includes(args.appearance)) throw new Error('Unbekannte Darstellung.');
      appearance.setStyle(args.appearance);
    } else if (action.name === 'set_cut') {
      const index = cutAxes.indexOf(args.axis);
      if (index < 0 || !Number.isFinite(args.min) || !Number.isFinite(args.max) || args.min < 0 || args.max > 100 || args.min > args.max) throw new Error('Ungültige Schnittgrenzen.');
      cutInputs[index].min.value = args.min;
      cutInputs[index].max.value = args.max;
      updateCuts();
      faceCut(args.axis);
    } else if (action.name === 'reset_view') {
      mentionGlow.clear();
      for (const region of regions) {
        if (region.object) setRegionOpacity(region, 1, false);
      }
      setAllRegions(true);
      selectRegions([]);
      document.getElementById('reset-cuts').click();
      fitCamera();
    }
    updateRegionCount();
    requestRender();
    const state = this.getState();
    if (focusing) {
      // Check the actual scene/material settings before reporting success.
      for (const region of regions) {
        if (!region.object) continue;
        const target = selected.includes(region);
        const visible = !region.optIn || target;
        const opacity = target || !visible ? 1 : appearance.getContextOpacity();
        let valid = region.object.visible === visible && region.highlighted === target;
        region.object.traverse(child => {
          if (child.isMesh && child.material.opacity !== opacity) valid = false;
        });
        if (!valid) throw new Error('Die sichtbare Hervorhebung konnte nicht bestätigt werden.');
      }
      if (Object.values(state.cuts).some(([min, max]) => min !== 0 || max !== 100)) {
        throw new Error('Vorherige Schnitte konnten nicht zurückgesetzt werden.');
      }
    }
    return state;
  },
  describe(action) {
    const focusLabel = `Zielareale hervorgehoben (Umgebung ${Math.round(appearance.getContextOpacity() * 100)} %)`;
    const labels = { highlight_regions: action.arguments.region_ids?.length ? focusLabel : 'Auswahl aufgehoben', set_visibility: 'Sichtbarkeit geändert',
      set_opacity: `Deckkraft: ${Math.round(action.arguments.opacity * 100)} %`,
      set_appearance: `Darstellung: ${{ learning: 'Lernansicht', natural: 'Natürlich', digital: 'Digital' }[action.arguments.appearance]}`,
      isolate_regions: focusLabel, set_cut: 'Schnitt eingestellt', reset_view: 'Ansicht zurückgesetzt' };
    return labels[action.name] + (action.arguments.region_ids?.length ? ': ' + action.arguments.region_ids.join(', ') : '');
  },
};
if (loaded) attachViewer(assistantViewer);

if (loaded) attachGestureControl({
  camera, controls, requestRender,
  onGrab() {
    rotationToggle.checked = false;
    resumeRotationAfterCuts = false;
    lastFrameTime = null;
    requestRender();
  },
  onRelease() {
    rotationToggle.checked = true;
    resumeRotationAfterCuts = false;
    lastFrameTime = null;
    requestRender();
  },
});
