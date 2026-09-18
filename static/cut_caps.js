import { tissueNoiseGLSL } from './tissue_appearance.js';

// Stencil cross-sections share the surface geometry's GPU buffers.
export function createCutCaps(THREE, scene, brain, planes) {
  brain.updateMatrixWorld(true);
  const entries = [];
  const capGeometry = new THREE.PlaneGeometry(1, 1);
  let order = 1;
  const surfaces = [];
  brain.traverse(surface => {
    if (surface.isMesh) surfaces.push(surface);
  });
  // Outer shells first, smaller structures last: overlapping anatomical
  // exports should not obscure all inner labels on the same cut plane.
  const volume = surface => {
    surface.geometry.computeBoundingBox();
    const size = surface.geometry.boundingBox.getSize(new THREE.Vector3());
    return size.x * size.y * size.z;
  };
  surfaces.sort((a, b) => volume(b) - volume(a));
  surfaces.forEach((surface, regionIndex) => {
    surface.geometry.computeBoundingBox();
    const bounds = surface.geometry.boundingBox.clone().applyMatrix4(surface.matrixWorld);
    const size = bounds.getSize(new THREE.Vector3()).length() * 1.05;
    const center = bounds.getCenter(new THREE.Vector3());
    planes.forEach(plane => {
      const group = new THREE.Group();
      group.visible = false;
      const base = {
        depthWrite: false, depthTest: false, colorWrite: false,
        stencilWrite: true, stencilFunc: THREE.AlwaysStencilFunc,
        clippingPlanes: [plane],
      };
      for (const [side, operation] of [
        [THREE.BackSide, THREE.IncrementWrapStencilOp],
        [THREE.FrontSide, THREE.DecrementWrapStencilOp],
      ]) {
        const material = new THREE.MeshBasicMaterial({ ...base, side,
          stencilFail: operation, stencilZFail: operation, stencilZPass: operation });
        const mesh = new THREE.Mesh(surface.geometry, material);
        mesh.matrixAutoUpdate = false;
        mesh.matrix.copy(surface.matrixWorld);
        mesh.renderOrder = order++;
        mesh.frustumCulled = false;
        group.add(mesh);
      }
      const material = new THREE.MeshBasicMaterial({
        color: surface.material.color, side: THREE.DoubleSide,
        clippingPlanes: planes.filter(other => other !== plane),
        stencilWrite: true, stencilRef: 0, stencilFunc: THREE.NotEqualStencilFunc,
        stencilFail: THREE.ReplaceStencilOp, stencilZFail: THREE.ReplaceStencilOp,
        stencilZPass: THREE.ReplaceStencilOp,
        // Deterministic depth priority for coplanar, overlapping region caps.
        polygonOffset: true, polygonOffsetFactor: 0, polygonOffsetUnits: -(regionIndex + 1) * 2,
      });
      // The cut has its own muted tissue palette; other appearances retain
      // their surface colors. Share the style uniform so switching updates it.
      material.onBeforeCompile = shader => {
        shader.uniforms.cutTissue = surface.material.userData.appearance?.tissue ?? { value: 0 };
        shader.vertexShader = shader.vertexShader
          .replace('#include <common>', '#include <common>\nvarying vec3 vCutPosition;')
          .replace('#include <begin_vertex>', `#include <begin_vertex>
            vCutPosition = (modelMatrix * vec4(transformed, 1.0)).xyz;`);
        shader.fragmentShader = shader.fragmentShader
          .replace('#include <common>', `#include <common>
            varying vec3 vCutPosition;
            uniform float cutTissue;
            ${tissueNoiseGLSL}`)
          .replace('#include <color_fragment>', `#include <color_fragment>
            if (cutTissue > 0.5) {
              diffuseColor.rgb *= 0.94 + 0.12 * tissueNoise(vCutPosition * 1.3);
            }`);
      };
      material.customProgramCacheKey = () => 'brain-cut-tissue-v1';
      const cap = new THREE.Mesh(capGeometry, material);
      cap.scale.setScalar(size);
      cap.renderOrder = order++;
      cap.frustumCulled = false;
      cap.onAfterRender = renderer => renderer.clearStencil();
      group.add(cap);
      scene.add(group);
      entries.push({ surface, bounds, center, plane, group, cap });
    });
  });
  const forward = new THREE.Vector3(0, 0, 1);
  return {
    update(enabled) {
      for (const entry of entries) {
        entry.cap.material.color.copy(entry.surface.material.userData.cutColor ?? entry.surface.material.color);
        const opacity = entry.surface.material.opacity * (entry.surface.material.userData.cutOpacityScale ?? 1);
        const transparent = opacity < 1;
        // Keep each stencil pair and its cap in the same render queue.
        // Otherwise all transparent caps would consume the last region's stencil.
        for (const child of entry.group.children) {
          if (child.material.transparent !== transparent) child.material.needsUpdate = true;
          child.material.transparent = transparent;
        }
        entry.cap.material.opacity = opacity;
        entry.cap.material.depthWrite = !transparent;
        let visible = enabled && opacity > 0;
        for (let node = entry.surface; node && visible; node = node.parent) visible = node.visible;
        entry.group.visible = visible && entry.bounds.intersectsPlane(entry.plane);
        if (!entry.group.visible) continue;
        entry.plane.projectPoint(entry.center, entry.cap.position);
        entry.cap.quaternion.setFromUnitVectors(forward, entry.plane.normal);
      }
    },
  };
}
