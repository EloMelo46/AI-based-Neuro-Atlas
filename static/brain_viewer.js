import * as THREE from 'three';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createCutCaps } from './cut_caps.js';
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
scene.background = new THREE.Color(0x10141c);
const brain = new THREE.Group();
// FreeSurfer RAS: Z points superior; Three.js: Y points up.
brain.rotation.x = -Math.PI / 2;
scene.add(brain);
const sceneHost = document.getElementById('scene');
const camera = new THREE.PerspectiveCamera(45, sceneHost.clientWidth / sceneHost.clientHeight, 0.1, 2000);
const renderer = new THREE.WebGLRenderer({ antialias: true, stencil: true });
renderer.localClippingEnabled = true;
renderer.setPixelRatio(1);
renderer.setSize(sceneHost.clientWidth, sceneHost.clientHeight);
sceneHost.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
const rotationToggle = document.getElementById('auto-rotate');
let interacting = false;
let lastFrameTime = null;
const rotationOffset = new THREE.Vector3();
controls.addEventListener('start', () => { interacting = true; });
controls.addEventListener('end', () => { interacting = false; lastFrameTime = null; requestRender(); });
rotationToggle.addEventListener('change', () => { lastFrameTime = null; requestRender(); });
document.addEventListener('visibilitychange', () => {
  lastFrameTime = null;
  if (!document.hidden) requestRender();
});
let framePending = false;
let caps = null;
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
    renderer.render(scene, camera);
    if (rotating) requestRender();
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
scene.add(new THREE.HemisphereLight(0xffffff, 0x69758c, 1.2));
const light = new THREE.DirectionalLight(0xffffff, 1);
light.position.set(1, 2, 3);
scene.add(light);
let loaded = 0;
let failed = 0;

// Keep the sorted file order and share each color between mesh and legend.
const regions = names.map((name, index) => {
  const color = new THREE.Color().setHSL((index * 0.61803398875) % 1, 0.65, 0.6);
  const checkbox = document.getElementById(`region-${index}`);
  const state = document.getElementById(`region-state-${index}`);
  document.getElementById(`region-color-${index}`).style.backgroundColor = color.getStyle();
  const region = { color, checkbox, state, object: null, optIn: name === 'CSF.obj' };
  checkbox.addEventListener('change', () => {
    if (region.object) region.object.visible = checkbox.checked;
    updateRegionCount();
  });
  return region;
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

cutInputs.forEach(inputs => {
  for (const bound of ['min', 'max']) {
    inputs[bound].addEventListener('input', () => {
      // Move the opposite endpoint along if the handles cross.
      if (Number(inputs.min.value) > Number(inputs.max.value)) {
        inputs[bound === 'min' ? 'max' : 'min'].value = inputs[bound].value;
      }
      updateCuts();
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
  updateCuts();
  cutAxes.forEach(axis => { document.getElementById(`cut-${axis}`).disabled = false; });
  document.getElementById('reset-cuts').disabled = false;
}

function fitCamera(targetBounds = null) {
  const bounds = targetBounds instanceof THREE.Box3 ? targetBounds : new THREE.Box3().setFromObject(brain);
  if (bounds.isEmpty()) return;
  const sphere = bounds.getBoundingSphere(new THREE.Sphere());
  const vertical = THREE.MathUtils.degToRad(camera.fov) / 2;
  const horizontal = Math.atan(Math.tan(vertical) * camera.aspect);
  const radius = Math.max(sphere.radius, 0.01);
  // The bounding sphere guarantees that every region stays inside the frame;
  // retain only a slim two-percent visual safety margin around it.
  const distance = radius / Math.sin(Math.min(vertical, horizontal)) * 0.7;
  controls.target.copy(sphere.center);
  camera.position.copy(sphere.center).add(new THREE.Vector3(0.5, 0.3, 1).normalize().multiplyScalar(distance));
  camera.near = radius / 1000;
  camera.far = distance + radius * 100;
  camera.updateProjectionMatrix();
  controls.minDistance = radius * 0.2;
  controls.maxDistance = radius * 5;
  controls.update();
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
      child.material = new THREE.MeshPhongMaterial({
        color: regions[index].color,
        side: THREE.DoubleSide,
        shininess: 20,
        transparent: false,
        opacity: 1,
        depthWrite: true,
        clippingPlanes: cutPlanes,
      });
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

function setRegionOpacity(region, opacity, makeVisible = true) {
  region.opacity = opacity;
  if (makeVisible) {
    region.object.visible = true;
    region.checkbox.checked = true;
  }
  region.object.traverse(child => {
    if (!child.isMesh) return;
    const transparent = opacity < 1;
    if (child.material.transparent !== transparent) child.material.needsUpdate = true;
    child.material.opacity = opacity;
    child.material.transparent = transparent;
    child.material.depthWrite = !transparent;
  });
  region.state.textContent = opacity < 1 ? `${Math.round(opacity * 100)} % deckend` : '';
}

function selectRegions(selected) {
  for (const region of regions) {
    if (!region.object) continue;
    region.highlighted = selected.includes(region);
    region.object.traverse(child => {
      if (!child.isMesh) return;
      child.material.color.copy(region.color);
      child.material.emissive.set(0x000000);
    });
  }
}

export const assistantViewer = {
  getState() {
    const matching = predicate => [...regionMap].filter(([, region]) => region.object && predicate(region)).map(([id]) => id);
    return {
      loaded: matching(() => true), visible: matching(region => region.object.visible),
      highlighted: matching(region => region.highlighted),
      opacities: Object.fromEntries([...regionMap].filter(([, region]) => region.object).map(([id, region]) => [id, region.opacity ?? 1])),
      cuts: Object.fromEntries(cutAxes.map((axis, index) => [axis, [Number(cutInputs[index].min.value), Number(cutInputs[index].max.value)]])),
    };
  },
  execute(action) {
    const args = action.arguments;
    const allowed = ['highlight_regions', 'set_visibility', 'set_opacity', 'isolate_regions', 'set_cut', 'reset_view'];
    if (!allowed.includes(action.name) || !args || typeof args !== 'object') throw new Error('Unbekannte Vieweraktion.');
    const selected = (args.region_ids ?? []).map(id => {
      const region = regionMap.get(id);
      if (!region?.object) throw new Error(`Areal nicht geladen: ${id}`);
      return region;
    });
    if (action.name === 'highlight_regions') {
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
    } else if (action.name === 'isolate_regions') {
      if (!selected.length) throw new Error('Keine Zielregion.');
      selectRegions(selected);
      for (const region of regions) {
        if (!region.object) continue;
        if (region.optIn && !selected.includes(region)) {
          setRegionOpacity(region, 1, false);
          region.object.visible = false;
          region.checkbox.checked = false;
        } else {
          setRegionOpacity(region, selected.includes(region) ? 1 : 0.01);
        }
      }
      // Keep the full brain in frame instead of zooming onto the selected anatomy.
      fitCamera();
    } else if (action.name === 'set_cut') {
      const index = cutAxes.indexOf(args.axis);
      if (index < 0 || !Number.isFinite(args.min) || !Number.isFinite(args.max) || args.min < 0 || args.max > 100 || args.min > args.max) throw new Error('Ungültige Schnittgrenzen.');
      cutInputs[index].min.value = args.min;
      cutInputs[index].max.value = args.max;
      updateCuts();
    } else if (action.name === 'reset_view') {
      for (const region of regions) {
        if (region.object) setRegionOpacity(region, 1, false);
      }
      setAllRegions(true);
      this.execute({ name: 'highlight_regions', arguments: { region_ids: [] } });
      document.getElementById('reset-cuts').click();
      fitCamera();
    }
    updateRegionCount();
    requestRender();
  },
  describe(action) {
    const labels = { highlight_regions: 'Markierung aktualisiert', set_visibility: 'Sichtbarkeit geändert',
      set_opacity: `Deckkraft: ${Math.round(action.arguments.opacity * 100)} %`,
      isolate_regions: 'Zielareale hervorgehoben (Umgebung 1 %)', set_cut: 'Schnitt eingestellt', reset_view: 'Ansicht zurückgesetzt' };
    return labels[action.name] + (action.arguments.region_ids?.length ? ': ' + action.arguments.region_ids.join(', ') : '');
  },
};
if (loaded) attachViewer(assistantViewer);
