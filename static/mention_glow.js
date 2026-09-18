// Narration is a separate overlay: no edits to region visibility/materials/selection.
export function createMentionGlow(THREE, scene, regionMap, cutPlanes, requestRender, getAppearance = () => 'learning') {
  const active = new Map();
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const duration = 2000;
  function remove(id) {
    const entry = active.get(id);
    if (!entry) return;
    clearTimeout(entry.timer);
    for (const { overlay } of entry.meshes) {
      scene.remove(overlay);
      overlay.material.dispose();
      // Geometry belongs to the anatomical mesh and must stay alive.
    }
    active.delete(id);
  }
  function glow(ids) {
    const now = performance.now();
    for (const id of new Set(ids)) {
      const region = regionMap.get(id);
      if (!region?.object || (region.optIn && !region.object.visible)) continue;
      remove(id);
      const meshes = [];
      region.object.updateWorldMatrix(true, true);
      region.object.traverse(surface => {
        if (!surface.isMesh) return;
        const material = new THREE.ShaderMaterial({
          uniforms: {
            strength: { value: 0 }, glowColor: { value: new THREE.Color(0xffe6a3) },
            softness: surface.material.userData.appearance?.softness ?? { value: 0 },
          },
          vertexShader: `
            attribute vec3 brainSoftNormal;
            uniform float softness;
            varying vec3 surfaceNormal;
            varying vec3 viewDirection;
            #include <clipping_planes_pars_vertex>
            void main() {
              vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
              surfaceNormal = normalize(normalMatrix * mix(normal, brainSoftNormal, softness));
              viewDirection = -mvPosition.xyz;
              gl_Position = projectionMatrix * mvPosition;
              #include <clipping_planes_vertex>
            }`,
          fragmentShader: `
            uniform float strength;
            uniform vec3 glowColor;
            varying vec3 surfaceNormal;
            varying vec3 viewDirection;
            #include <clipping_planes_pars_fragment>
            void main() {
              #include <clipping_planes_fragment>
              float rim = pow(1.0 - abs(dot(normalize(surfaceNormal), normalize(viewDirection))), 2.0);
              gl_FragColor = vec4(glowColor, strength * (0.22 + 0.78 * rim));
            }`,
          clipping: true, clippingPlanes: cutPlanes,
          transparent: true, depthTest: false, depthWrite: false,
          blending: THREE.AdditiveBlending, side: THREE.FrontSide,
        });
        material.defaultAttributeValues.brainSoftNormal = [0, 0, 1];
        const overlay = new THREE.Mesh(surface.geometry, material);
        overlay.matrixAutoUpdate = false;
        overlay.matrix.copy(surface.matrixWorld);
        overlay.renderOrder = 10000;
        scene.add(overlay);
        meshes.push({ surface, overlay });
      });
      const timer = setTimeout(() => { remove(id); requestRender(); }, duration);
      active.set(id, { meshes, region, started: now, timer });
    }
    requestRender();
  }
  function clear() {
    for (const id of active.keys()) remove(id);
    requestRender();
  }
  function update(time) {
    const styled = getAppearance() !== 'learning';
    for (const [id, entry] of active) {
      const elapsed = time - entry.started;
      if (elapsed >= duration || (entry.region.optIn && !entry.region.object.visible)) {
        remove(id);
        continue;
      }
      const fade = Math.min(1, elapsed / 160, (duration - elapsed) / 350);
      const pulse = reducedMotion.matches ? 0.65 : 0.55 + 0.25 * Math.cos(elapsed * Math.PI * 2 / 1200);
      for (const { surface, overlay } of entry.meshes) {
        surface.updateWorldMatrix(true, false);
        overlay.matrix.copy(surface.matrixWorld);
        // With dense overlapping cortex surfaces, additive glow accumulates to
        // white. The new appearances use a bounded warm tint instead.
        overlay.material.blending = styled ? THREE.NormalBlending : THREE.AdditiveBlending;
        overlay.material.uniforms.glowColor.value.set(styled ? 0xffb45d : 0xffe6a3);
        overlay.material.uniforms.strength.value = fade * pulse * (styled ? 0.65 : 1);
      }
    }
    return active.size > 0;
  }
  window.addEventListener('pagehide', clear);
  return { glow, clear, update, getActiveIds: () => [...active.keys()] };
}
