import { naturalCutColor, prepareTissueVariation } from './tissue_appearance.js';

// Appearance changes reuse geometry and preserve anatomical selection and cuts.
const STORAGE_KEY = 'neuroatlas.appearance';
const softenedGeometries = new WeakSet();

function softenNormals(THREE, geometry) {
  if (softenedGeometries.has(geometry)) return;
  const normals = geometry.getAttribute('normal');
  const indices = geometry.index?.array;
  if (!normals || !indices) return;
  let previous = new Float32Array(normals.array);
  let next = new Float32Array(previous.length);
  // Average nearby normal directions, not vertex positions. This softens the
  // voxel/decimation facets while retaining every anatomical boundary and cut.
  // Opposing normals across a crease cannot cancel one another.
  function addEdge(a, b) {
    a *= 3; b *= 3;
    const dot = previous[a] * previous[b] + previous[a + 1] * previous[b + 1]
      + previous[a + 2] * previous[b + 2];
    const weight = Math.max(0, dot) ** 2;
    for (let axis = 0; axis < 3; axis++) {
      next[a + axis] += previous[b + axis] * weight;
      next[b + axis] += previous[a + axis] * weight;
    }
  }
  for (let pass = 0; pass < 3; pass++) {
    for (let i = 0; i < previous.length; i++) next[i] = previous[i] * 2;
    for (let i = 0; i < indices.length; i += 3) {
      addEdge(indices[i], indices[i + 1]);
      addEdge(indices[i + 1], indices[i + 2]);
      addEdge(indices[i + 2], indices[i]);
    }
    for (let i = 0; i < next.length; i += 3) {
      const length = Math.hypot(next[i], next[i + 1], next[i + 2]) || 1;
      next[i] /= length; next[i + 1] /= length; next[i + 2] /= length;
    }
    [previous, next] = [next, previous];
  }
  geometry.setAttribute('brainSoftNormal', new THREE.BufferAttribute(previous, 3));
  softenedGeometries.add(geometry);
}

const STYLES = {
  learning: {
    color: null, specular: 0x111111, shininess: 20,
    emissive: 0x000000, rim: 0x000000, rimStrength: 0,
    sky: 0xffffff, ground: 0x69758c, ambient: 1.2,
    key: 0xffffff, keyStrength: 1, keyPosition: [1, 2, 3],
    fill: 0xffffff, fillStrength: 0, edge: 0xffffff, edgeStrength: 0,
  },
  natural: {
    color: 0xc9a09e, specular: 0x000000, shininess: 1,
    emissive: 0x000000, rim: 0x000000, rimStrength: 0,
    sky: 0xfff4ec, ground: 0x433430, ambient: 0.75,
    key: 0xfff4ec, keyStrength: 1.05, keyPosition: [-3, 4, 5],
    fill: 0xe0e3e8, fillStrength: 0.32, edge: 0xffe2cd, edgeStrength: 0.35,
  },
  digital: {
    color: 0x123c79, specular: 0x000000, shininess: 1,
    emissive: 0x000000, rim: 0x55dfff, rimStrength: 0,
    sky: 0x92caff, ground: 0x030b22, ambient: 0.55,
    key: 0x9bcaff, keyStrength: 1.1, keyPosition: [-2, 3, 4],
    fill: 0x487cec, fillStrength: 0.45, edge: 0x67dcff, edgeStrength: 0.85,
  },
};

export function createBrainAppearance(THREE, scene, regions, requestRender, onStyleChange) {
  const select = document.getElementById('appearance');
  // Use the settings of the running server, which also validates tool results.
  // Older server pages without this configuration expect 3% in every style.
  const contextOpacities = JSON.parse(document.getElementById('focus-context-opacities')?.textContent ?? '{}');
  const center = { value: new THREE.Vector3() };
  const radius = { value: 100 };
  let current = 'learning';
  let cutsActive = false;
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (Object.hasOwn(STYLES, saved)) current = saved;
  } catch { /* Storage may be disabled; the selector still works. */ }

  const hemisphere = new THREE.HemisphereLight();
  const key = new THREE.DirectionalLight();
  const fill = new THREE.DirectionalLight();
  const edge = new THREE.DirectionalLight();
  fill.position.set(4, 1, 0);
  edge.position.set(0, 2, -4);
  scene.add(hemisphere, key, fill, edge);

  function regionColor(region) {
    if (current === 'learning') return region.color;
    return current === 'digital' && region.highlighted ? 0xf2a060 : STYLES[current].color;
  }

  function applyMaterial(material, region) {
    const style = STYLES[current];
    const digital = current === 'digital';
    const warm = current === 'digital' && region.highlighted;
    const transparent = digital || material.opacity < 1;
    const side = digital ? THREE.FrontSide : THREE.DoubleSide;
    if (material.transparent !== transparent || material.side !== side) material.needsUpdate = true;
    material.transparent = transparent;
    material.depthWrite = !transparent;
    material.side = side;
    material.userData.cutOpacityScale = digital ? 0.18 : 1;
    material.userData.cutColor ??= new THREE.Color();
    material.userData.cutColor.set(current === 'natural' ? naturalCutColor(region.id) : regionColor(region));
    material.color.set(regionColor(region));
    material.specular.set(style.specular);
    material.shininess = style.shininess;
    material.emissive.set(style.emissive);
    material.userData.appearance.rimColor.value.set(warm ? 0xffce88 : style.rim);
    material.userData.appearance.rimStrength.value = style.rimStrength;
    material.userData.appearance.tissue.value = current === 'natural' ? 1 : 0;
    material.userData.appearance.softness.value = current === 'learning' ? 0 : 0.9;
    material.userData.appearance.digital.value = digital ? 1 : 0;
    material.userData.appearance.focus.value = warm ? 1 : 0;
  }

  function createMaterial(region, clippingPlanes, geometry) {
    geometry.setAttribute('brainSoftNormal', geometry.getAttribute('normal'));
    geometry.setAttribute('brainTissueVariation', new THREE.BufferAttribute(
      new Float32Array(geometry.getAttribute('position').count).fill(0.5), 1));
    if (current === 'natural') prepareTissueVariation(THREE, geometry);
    if (current !== 'learning') softenNormals(THREE, geometry);
    const material = new THREE.MeshPhongMaterial({
      side: THREE.DoubleSide, clippingPlanes,
      transparent: false, opacity: 1, depthWrite: true,
    });
    material.extensions = { derivatives: true };
    const uniforms = {
      rimColor: { value: new THREE.Color() },
      rimStrength: { value: 0 },
      tissue: { value: 0 },
      softness: { value: 0 },
      digital: { value: 0 },
      focus: { value: 0 },
    };
    material.userData.appearance = uniforms;
    // Extend the pinned r152 Phong shader so clipping, lighting, depth and
    // assistant opacity keep the same meaning. The hologram shares the geometry
    // and draw call, but uses emitted light and patterned alpha instead of Phong.
    material.onBeforeCompile = shader => {
      shader.uniforms.brainRimColor = uniforms.rimColor;
      shader.uniforms.brainRimStrength = uniforms.rimStrength;
      shader.uniforms.brainTissue = uniforms.tissue;
      shader.uniforms.brainSoftness = uniforms.softness;
      shader.uniforms.brainDigital = uniforms.digital;
      shader.uniforms.brainFocus = uniforms.focus;
      shader.uniforms.brainCenter = center;
      shader.uniforms.brainRadius = radius;
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', `#include <common>
          varying vec3 vBrainPosition;
          varying float vBrainDepth;
          uniform vec3 brainCenter;
          attribute vec3 brainSoftNormal;
          attribute float brainTissueVariation;
          varying float vBrainTissueVariation;
          uniform float brainSoftness;`)
        .replace('#include <beginnormal_vertex>', `#include <beginnormal_vertex>
          objectNormal = mix(objectNormal, brainSoftNormal, brainSoftness);`)
        .replace('#include <begin_vertex>', '#include <begin_vertex>\nvBrainPosition = position;\nvBrainTissueVariation = brainTissueVariation;')
        .replace('#include <project_vertex>', `#include <project_vertex>
          vBrainDepth = -mvPosition.z + (modelViewMatrix * vec4(brainCenter, 1.0)).z;`);
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', `#include <common>
          varying vec3 vBrainPosition;
          varying float vBrainDepth;
          uniform float brainRadius;
          uniform vec3 brainRimColor;
          uniform float brainRimStrength;
          uniform float brainTissue;
          uniform float brainDigital;
          uniform float brainFocus;
          varying float vBrainTissueVariation;`)
        .replace('#include <color_fragment>', `#include <color_fragment>
          if (brainTissue > 0.5) {
            diffuseColor.rgb *= mix(vec3(0.87, 0.80, 0.77), vec3(1.11, 1.08, 1.04), vBrainTissueVariation);
          }`)
        .replace('#include <output_fragment>', `
          float brainFacing = clamp(abs(dot(normal, normalize(vViewPosition))), 0.0, 1.0);
          float brainRim = pow(1.0 - brainFacing, 3.0);
          // Translucent context should not veil focused regions in cyan.
          outgoingLight += brainRimColor * brainRimStrength * brainRim * opacity;
          if (brainDigital > 0.5) {
            // Object-space lines follow the anatomy as the camera rotates.
            // Derivatives soften their edges at small sizes and high resolution.
            float scanPosition = vBrainPosition.z * 0.32;
            float scanDistance = abs(fract(scanPosition) - 0.5);
            float scanWidth = max(fwidth(scanPosition), 0.015);
            float scanLine = 1.0 - smoothstep(0.035, 0.035 + scanWidth, scanDistance);
            float contour = pow(1.0 - brainFacing, 2.2);
            float coverage = 0.025 + 0.38 * contour + 0.17 * scanLine;
            coverage = mix(coverage, 0.2 + 0.55 * contour + 0.2 * scanLine, brainFocus);
            // Fade distant layers to keep the front folds readable. Focused
            // anatomy remains bright even when it lies deep inside the brain.
            float layerDepth = clamp((vBrainDepth + brainRadius * 0.8) / (brainRadius * 1.6), 0.0, 1.0);
            coverage *= mix(exp(-3.5 * layerDepth), 1.0, brainFocus);
            outgoingLight = brainRimColor * (0.32 + 0.8 * contour + 0.3 * scanLine);
            diffuseColor.a = opacity * clamp(coverage, 0.0, 0.9);
          }
          #include <output_fragment>`);
    };
    material.customProgramCacheKey = () => 'brain-appearance-v4-baked-tissue';
    applyMaterial(material, region);
    return material;
  }

  function applyRegion(region) {
    region.object?.traverse(surface => {
      if (!surface.isMesh) return;
      if (current !== 'learning') softenNormals(THREE, surface.geometry);
      if (current === 'natural') prepareTissueVariation(THREE, surface.geometry);
      applyMaterial(surface.material, region);
    });
    updateSwatch(region);
  }

  function updateSwatch(region) {
    const color = current === 'natural' && cutsActive ? naturalCutColor(region.id) : regionColor(region);
    region.swatch.style.backgroundColor = new THREE.Color(color).getStyle();
  }

  function applyStyle() {
    const style = STYLES[current];
    select.value = current;
    document.body.dataset.appearance = current;
    hemisphere.color.set(style.sky);
    hemisphere.groundColor.set(style.ground);
    hemisphere.intensity = style.ambient;
    key.color.set(style.key);
    key.intensity = style.keyStrength;
    key.position.set(...style.keyPosition);
    fill.color.set(style.fill);
    fill.intensity = style.fillStrength;
    edge.color.set(style.edge);
    edge.intensity = style.edgeStrength;
    regions.forEach(applyRegion);
    requestRender();
  }

  select.addEventListener('change', () => {
    if (!Object.hasOwn(STYLES, select.value)) return;
    current = select.value;
    try { localStorage.setItem(STORAGE_KEY, current); } catch { /* Optional persistence. */ }
    applyStyle();
    onStyleChange?.();
  });
  applyStyle();
  return {
    createMaterial, applyRegion, getStyle: () => current,
    getContextOpacity: () => contextOpacities[current] ?? 0.03,
    setCutsActive(active) {
      if (cutsActive === active) return;
      cutsActive = active;
      regions.forEach(updateSwatch);
    },
    setBounds(bounds) {
      bounds.getCenter(center.value);
      radius.value = Math.max(bounds.getSize(new THREE.Vector3()).length() / 2, 1);
    },
  };
}
