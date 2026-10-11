import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createCutCaps } from './cut_caps.js';
import { createCutCulling } from './cut_culling.js';
import { createCutDepthPrepass } from './cut_depth_prepass.js';
import { createMentionGlow } from './mention_glow.js';
import { createBrainAppearance } from './brain_appearance.js';
import { attachGestureControl } from './gesture_control.js';
import { attachViewer } from './assistant_bridge.js';

const status = document.getElementById('status');
const errors = document.getElementById('errors');
const manifest = JSON.parse(document.getElementById('mesh-list').textContent);
const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);
const scene = new THREE.Scene();
// Transparent canvas lets each appearance use a subtle CSS backdrop.
const brain = new THREE.Group();
// FreeSurfer RAS: Z points superior; Three.js: Y points up.
brain.rotation.x = -Math.PI / 2;
scene.add(brain);
const sceneHost = document.getElementById('scene');
const camera = new THREE.PerspectiveCamera(45, sceneHost.clientWidth / sceneHost.clientHeight, 0.1, 2000);
const renderer = new THREE.WebGLRenderer({ antialias: true, stencil: true, alpha: true });
// Region colors require separate materials. Depth before material ID reduces
// opaque overdraw while retaining the explicit depth/stencil/cap render order.
renderer.setOpaqueSort((a, b) => a.groupOrder - b.groupOrder || a.renderOrder - b.renderOrder
  || a.z - b.z || a.material.id - b.material.id || a.id - b.id);
renderer.localClippingEnabled = true;
renderer.setPixelRatio(window.devicePixelRatio || 1);
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
let cutCulling = null;
let depthPrepass = null;
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
    depthPrepass?.update();
    caps?.update(document.getElementById('fill-cuts').checked, camera);
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
  const ratio = window.devicePixelRatio || 1;
  if (renderer.getPixelRatio() !== ratio) renderer.setPixelRatio(ratio);
}
// Moving between displays can change pixel density without changing CSS size.
let displayDensity;
function watchDisplayDensity() {
  displayDensity?.removeEventListener('change', watchDisplayDensity);
  updateResolution();
  displayDensity = matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`);
  displayDensity.addEventListener('change', watchDisplayDensity);
  requestRender();
}
watchDisplayDensity();
document.getElementById('fill-cuts').addEventListener('change', requestRender);
let loaded = 0;
let failed = 0;
let cutsActive = false;
let framedCutBounds = null;

// Keep sorted file order and retain the original learning color for every region.
const regions = manifest.map((metadata, index) => {
  const color = new THREE.Color().setHSL((index * 0.61803398875) % 1, 0.65, 0.6);
  const checkbox = document.getElementById(`region-${index}`);
  const state = document.getElementById(`region-state-${index}`);
  const swatch = document.getElementById(`region-color-${index}`);
  const region = { ...metadata, id: metadata.region_id, color, checkbox, state, swatch,
    object: null, optIn: metadata.default_visible === false,
    requestedVisible: metadata.default_visible !== false, sliceSuppressed: false, sliceOnly: false };
  if (metadata.cut_validation_note && state) {
    state.title = metadata.cut_validation_note;
    checkbox.closest('.region-row')?.setAttribute('title', `${metadata.region_id}: ${metadata.cut_validation_note}`);
  }
  checkbox?.addEventListener('change', () => {
    region.requestedVisible = checkbox.checked;
    region.sliceSuppressed = !checkbox.checked;
    syncRegionVisibility();
    updateRegionCount();
  });
  return region;
});

function syncRegionVisibility() {
  const anatomy = regions.filter(region => region.selectable !== false && region.category !== 'csf');
  // Faint focus context does not count as showing the complete brain. Technical
  // fills and optional CSF are not part of the required anatomical selection.
  const wholeBrainVisible = anatomy.length > 0 && anatomy.every(region =>
    region.object && region.requestedVisible && !region.focusContext
    && (region.opacity ?? 1) > 0 && region.visible_in_slice !== false);
  for (const region of regions) {
    region.sliceOnly = region.category === 'csf' && !region.requestedVisible && !region.sliceSuppressed
      && cutsActive && wholeBrainVisible && region.visible_in_slice !== false;
    if (region.object) {
      region.object.visible = (region.requestedVisible || region.sliceOnly)
        && (!cutsActive || region.visible_in_slice !== false);
      region.object.traverse(surface => {
        if (!surface.isMesh) return;
        // Automatic CSF contributes a section, without hiding anatomy behind a
        // large fluid shell. Stencil helpers still share this source geometry.
        for (const material of new Set([surface.material, surface.userData.appearanceMaterial,
          surface.userData.contextMaterial, surface.userData.digitalMaterial])) {
          if (material) material.visible = !region.sliceOnly;
        }
      });
    }
    if (region.checkbox) region.checkbox.checked = region.requestedVisible;
    if (region.state && region.object) region.state.textContent = region.sliceOnly ? 'Schnittfüllung'
      : (region.opacity ?? 1) < 1 ? `${Math.round(region.opacity * 100)} % deckend` : '';
  }
}
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
  const available = regions.filter(region => region.object && region.selectable !== false);
  const visible = available.filter(region => region.object.visible).length;
  document.getElementById('region-count').textContent =
    `${visible} von ${available.length} geladenen Arealen eingeblendet`;
}

function setAllRegions(visible) {
  regions.forEach(region => {
    // Remember the choice for surfaces whose download is still in progress.
    if (!region.object && region.state?.dataset.failed) return;
    const nextVisibility = visible && !region.optIn;
    if (visible && region.object && region.focusContext) setRegionOpacity(region, 1, false);
    region.requestedVisible = nextVisibility;
    region.sliceSuppressed = !visible;
  });
  syncRegionVisibility();
  updateRegionCount();
}
document.getElementById('show-regions').addEventListener('click', () => setAllRegions(true));
document.getElementById('hide-regions').addEventListener('click', () => setAllRegions(false));
document.getElementById('show-regions').disabled = regions.length === 0;
document.getElementById('hide-regions').disabled = regions.length === 0;
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
  cutsActive = hasCuts;
  if (!hasCuts) framedCutBounds = null;
  syncRegionVisibility();
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
  // Whole-brain viewing is the common Pi path: do not evaluate six inactive
  // clipping planes in every fragment. Recompile only when their count changes;
  // moving a slider updates the existing plane uniforms without CPU geometry work.
  const activePlanes = cutPlanes.filter((_, index) => {
    const inputs = cutInputs[Math.floor(index / 2)];
    return index % 2 === 0 ? Number(inputs.min.value) > 0 : Number(inputs.max.value) < 100;
  });
  for (const region of regions) region.object?.traverse(child => {
    if (!child.isMesh) return;
    for (const material of new Set([child.material, child.userData.appearanceMaterial,
      child.userData.contextMaterial, child.userData.digitalMaterial])) {
      if (!material) continue;
      if (material.clippingPlanes.length !== activePlanes.length) material.needsUpdate = true;
      material.clippingPlanes = activePlanes;
    }
  });
  cutCulling?.update(activePlanes);
  updateRegionCount();
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
  appearance.setBounds(cutBounds, brain.matrixWorld);
  updateCuts();
  cutAxes.forEach(axis => { document.getElementById(`cut-${axis}`).disabled = false; });
  document.getElementById('reset-cuts').disabled = false;
}

function cutFitDistance(bounds, direction, aspect, margin = 1.04) {
  // Fit the projected rectangle, rather than a sphere around its diagonal.
  // Only eight bounds corners are evaluated when a cut/viewport changes.
  const center = bounds.getCenter(new THREE.Vector3());
  const basis = new THREE.Matrix4().lookAt(center.clone().add(direction), center, camera.up);
  const right = new THREE.Vector3(), up = new THREE.Vector3(), outward = new THREE.Vector3();
  basis.extractBasis(right, up, outward);
  const vertical = Math.tan(THREE.MathUtils.degToRad(camera.getEffectiveFOV()) / 2);
  const horizontal = vertical * aspect;
  let distance = 0.01;
  for (const x of [bounds.min.x, bounds.max.x]) for (const y of [bounds.min.y, bounds.max.y])
    for (const z of [bounds.min.z, bounds.max.z]) {
      const offset = new THREE.Vector3(x, y, z).sub(center);
      distance = Math.max(distance, offset.dot(outward) + margin * Math.max(
        Math.abs(offset.dot(right)) / horizontal, Math.abs(offset.dot(up)) / vertical));
    }
  return distance;
}

// RAS anterior (+Y) becomes world -Z after the brain rotation: look from front-right.
function fitCamera(targetBounds = null, direction = new THREE.Vector3(0.5, 0.3, -1), margin = 0.6) {
  const cutView = targetBounds instanceof THREE.Box3;
  const bounds = cutView ? targetBounds : new THREE.Box3().setFromObject(brain);
  if (bounds.isEmpty()) return;
  const sphere = bounds.getBoundingSphere(new THREE.Sphere());
  const vertical = THREE.MathUtils.degToRad(camera.fov) / 2;
  const horizontal = Math.atan(Math.tan(vertical) * camera.aspect);
  const radius = Math.max(sphere.radius, 0.01);
  const distance = cutView ? cutFitDistance(bounds, direction, camera.aspect)
    : radius / Math.sin(Math.min(vertical, horizontal)) * margin;
  framedCutBounds = cutView ? bounds.clone() : null;
  // Consume any pending drag/pan damping before applying an explicit camera view.
  const damping = controls.enableDamping;
  controls.enableDamping = false;
  controls.update();
  controls.target.copy(sphere.center);
  camera.position.copy(sphere.center).add(direction.clone().normalize().multiplyScalar(distance));
  const offset = cutView ? 0 : radius * 0.05;
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
  fitCamera(faceBounds, normal);
}

function updateStatus() {
  status.textContent = `${loaded} von ${regions.length} Regionen geladen` +
    (failed ? ` · ${failed} fehlgeschlagen` : '') +
    (loaded + failed < regions.length ? ' …' : '');
}

async function loadRegion(region) {
  let object = null;
  try {
    const gltf = await loader.loadAsync(region.glb_url);
    // The actual export is glTF Y-up (X right, Y superior, Z posterior).
    // Restore RAS within the brain group so existing cut/assistant axes keep
    // X=sagittal, Y=coronal, Z=axial. Preserve every quantization node transform.
    object = new THREE.Group();
    object.rotation.x = Math.PI / 2;
    object.add(gltf.scene);
    object.updateMatrixWorld(true);
    let triangles = 0;
    object.traverse(child => {
      if (!child.isMesh) return;
      triangles += (child.geometry.index?.count ?? child.geometry.attributes.position?.count ?? 0) / 3;
      const oldMaterials = Array.isArray(child.material) ? child.material : [child.material];
      oldMaterials.forEach(material => material.dispose());
      if (!child.geometry.getAttribute('normal')) child.geometry.computeVertexNormals();
      child.material = appearance.createMaterial(region, [], child.geometry, child.matrixWorld);
      child.userData.cutEligible = region.cut_eligible === true;
      child.userData.cutPriority = region.category === 'csf' ? -2 : region.render_role === 'fill' ? -1 : 0;
    });
    if (!triangles) throw new Error('Datei enthält keine Dreiecksflächen.');
    object.name = region.id;
    object.visible = region.requestedVisible;
    brain.add(object);
    region.object = object;
    appearance.applyRegion(region);
    if (region.checkbox) region.checkbox.disabled = false;
    if (region.state) region.state.textContent = '';
    loaded++;
    if (loaded === 1) fitCamera();
  } catch (error) {
    if (object) disposeObject(object);
    failed++;
    if (region.checkbox) {
      region.checkbox.checked = false;
      region.checkbox.disabled = true;
      region.state.textContent = 'Fehler';
      region.state.dataset.failed = 'true';
    }
    const item = document.createElement('li');
    item.textContent = `${region.name ?? region.id}: ${error.message}`;
    errors.appendChild(item);
    console.error(region.id, error);
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
  if (newAngle > 0) {
    const direction = camera.position.clone().sub(controls.target).normalize();
    const scale = framedCutBounds
      ? cutFitDistance(framedCutBounds, direction, aspect) / cutFitDistance(framedCutBounds, direction, camera.aspect)
      : Math.sin(oldAngle) / Math.sin(newAngle);
    camera.position.sub(controls.target).multiplyScalar(scale).add(controls.target);
  }
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
await Promise.all(Array.from({ length: Math.min(4, regions.length) }, async () => {
  while (next < regions.length) {
    const index = next++;
    await loadRegion(regions[index]);
  }
}));
cutCulling = createCutCulling(THREE, brain);
fitCamera();
initializeCuts();
caps = createCutCaps(THREE, scene, brain, cutPlanes);
depthPrepass = createCutDepthPrepass(THREE, scene, brain);
requestRender();
document.getElementById('reset').disabled = loaded === 0;
if (!regions.length) status.textContent = 'Keine vollständigen GLB-Regionen im Manifest gefunden.';

const regionMap = new Map(regions.map(region => [region.id, region]));
mentionGlow = createMentionGlow(THREE, scene, regionMap, cutPlanes, requestRender, appearance.getStyle);

export function getRenderDiagnostics() {
  const buffers = new Set();
  brain.traverse(object => {
    if (!object.isMesh) return;
    for (const attribute of [...Object.values(object.geometry.attributes), object.geometry.index]) {
      if (attribute) buffers.add(attribute.isInterleavedBufferAttribute ? attribute.data : attribute);
    }
  });
  return {
    loadedRegions: loaded, failedRegions: failed,
    memory: { ...renderer.info.memory, programs: renderer.info.programs?.length ?? 0 },
    // Attribute/index upload payload only, excluding driver/framebuffer overhead.
    // Stencil helpers reuse these buffers; aliased/interleaved attributes count once.
    geometryBufferBytes: [...buffers].reduce((bytes, buffer) => bytes + buffer.array.byteLength, 0),
    render: { ...renderer.info.render },
    clipping: cutCulling?.getDiagnostics(),
    caps: caps?.getDiagnostics(),
    depthPrepass: depthPrepass?.getDiagnostics(),
    anatomicalBounds: { min: cutBounds.min.toArray(), max: cutBounds.max.toArray() },
  };
}

function disposeObject(object) {
  object.traverse(child => {
    if (!child.isMesh) return;
    child.geometry.dispose();
    const materials = Array.isArray(child.material) ? child.material : [child.material];
    for (const material of new Set([...materials, child.userData.appearanceMaterial,
      child.userData.contextMaterial, child.userData.digitalMaterial])) {
      material?.dispose();
    }
  });
  object.removeFromParent();
}
window.addEventListener('pagehide', event => {
  if (event.persisted) return; // Browser back/forward cache owns this live scene.
  displayDensity?.removeEventListener('change', watchDisplayDensity);
  mentionGlow?.clear();
  caps?.dispose();
  depthPrepass?.dispose();
  for (const region of regions) if (region.object) disposeObject(region.object);
  controls.dispose();
  renderer.dispose();
});

function setRegionOpacity(region, opacity, makeVisible = true, focusContext = false) {
  region.opacity = opacity;
  region.focusContext = focusContext;
  if (makeVisible) {
    region.requestedVisible = true;
    region.sliceSuppressed = false;
  }
  region.object.traverse(child => {
    if (!child.isMesh) return;
    child.material.opacity = opacity;
  });
  appearance.applyRegion(region);
  if (region.state) region.state.textContent = opacity < 1 ? `${Math.round(opacity * 100)} % deckend` : '';
}

function selectRegions(selected) {
  for (const region of regions) {
    if (!region.object) continue;
    region.highlighted = region.highlightable !== false && selected.includes(region);
    if (!selected.length) region.focusContext = false;
    appearance.applyRegion(region);
  }
}

export const assistantViewer = {
  glowRegions(ids) { mentionGlow.glow(ids); },
  clearMentionGlow() { mentionGlow.clear(); },
  getMentionedRegions() { return mentionGlow.getActiveIds(); },
  getState() {
    const matching = predicate => [...regionMap].filter(([, region]) => region.selectable !== false && region.object && predicate(region)).map(([id]) => id);
    return {
      appearance: appearance.getStyle(),
      loaded: matching(() => true), visible: matching(region => region.object.visible),
      highlighted: matching(region => region.highlighted),
      opacities: Object.fromEntries([...regionMap].filter(([, region]) => region.object && region.selectable !== false).map(([id, region]) => [id, region.opacity ?? 1])),
      cuts: Object.fromEntries(cutAxes.map((axis, index) => [axis, [Number(cutInputs[index].min.value), Number(cutInputs[index].max.value)]])),
    };
  },
  execute(action) {
    const args = action.arguments;
    const allowed = ['highlight_regions', 'set_visibility', 'set_opacity', 'isolate_regions', 'set_cut', 'set_appearance', 'reset_view'];
    if (!allowed.includes(action.name) || !args || typeof args !== 'object') throw new Error('Unbekannte Vieweraktion.');
    const selected = (args.region_ids ?? []).map(id => {
      const region = regionMap.get(id);
      if (!region?.object || region.selectable === false) throw new Error(`Areal nicht auswählbar: ${id}`);
      if (['highlight_regions', 'isolate_regions'].includes(action.name) && region.highlightable === false) throw new Error(`Areal nicht hervorhebbar: ${id}`);
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
          region.requestedVisible = args.visible;
          region.sliceSuppressed = !args.visible;
        }
      }
    } else if (focusing) {
      if (!selected.length) throw new Error('Keine Zielregion.');
      selectRegions(selected);
      for (const region of regions) {
        if (!region.object) continue;
        if (region.optIn && !selected.includes(region)) {
          setRegionOpacity(region, 1, false);
          region.requestedVisible = false;
          region.sliceSuppressed = false;
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
    syncRegionVisibility();
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
    const groups = action.selection_groups ?? [];
    const groupNames = groups.map(group => group.name);
    const notes = [...new Set([
      ...groups.filter(group => group.approximation).map(group => `DKT-basierte Annäherung: ${group.description}`),
      ...(action.selection_notes ?? []),
    ])];
    const regionNames = (action.arguments.region_ids ?? []).map(id => regionMap.get(id)?.name ?? id);
    return labels[action.name] + (regionNames.length ? ': ' + (groupNames.length ? groupNames : regionNames).join(', ') : '')
      + (notes.length ? '. ' + notes.join(' ') : '');
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
