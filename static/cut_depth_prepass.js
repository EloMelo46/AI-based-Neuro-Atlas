// Establish clipped depth with a cheap shader, then shade matching opaque
// fragments with depth writes disabled. This avoids expensive hidden-surface
// lighting on the Pi while retaining clipping at coincident label boundaries.
// Transparent materials keep their existing rendering path.
export function createCutDepthPrepass(THREE, scene, brain) {
  brain.updateMatrixWorld(true);
  const group = new THREE.Group();
  const entries = [];
  brain.traverse(surface => {
    if (!surface.isMesh) return;
    const material = new THREE.MeshBasicMaterial({ colorWrite: false, depthWrite: true, side: THREE.DoubleSide });
    const depth = new THREE.Mesh(surface.geometry, material);
    depth.matrixAutoUpdate = false;
    depth.matrix.copy(surface.matrixWorld);
    depth.renderOrder = -1;
    depth.visible = false;
    group.add(depth);
    const before = surface.onBeforeRender, after = surface.onAfterRender;
    const entry = { surface, depth, before, after, active: false, saved: null };
    surface.onBeforeRender = function (...args) {
      before.apply(this, args);
      if (!entry.active) return;
      const current = this.material;
      entry.saved = { material: current, depthFunc: current.depthFunc, depthWrite: current.depthWrite };
      current.depthWrite = false;
      current.depthFunc = THREE.EqualDepth;
    };
    surface.onAfterRender = function (...args) {
      if (entry.saved) {
        const { material, depthFunc, depthWrite } = entry.saved;
        material.depthFunc = depthFunc;
        material.depthWrite = depthWrite;
        entry.saved = null;
      }
      after.apply(this, args);
    };
    entries.push(entry);
  });
  scene.add(group);
  return {
    update(enabled = true) {
      for (const entry of entries) {
        const material = entry.surface.material;
        let visible = enabled && material.visible && !material.transparent && material.opacity === 1
          && material.depthTest && material.depthWrite
          && material.clippingPlanes?.length > 0;
        for (let node = entry.surface; node && visible; node = node.parent) visible = node.visible;
        entry.active = entry.depth.visible = Boolean(visible);
        entry.depth.material.clippingPlanes = material.clippingPlanes;
        entry.depth.material.side = material.side;
      }
    },
    getDiagnostics() {
      return { activeSurfaces: entries.filter(entry => entry.active).length,
        sharedSurfaceBuffers: entries.every(entry => entry.depth.geometry === entry.surface.geometry) };
    },
    dispose() {
      group.removeFromParent();
      for (const entry of entries) {
        entry.surface.onBeforeRender = entry.before;
        entry.surface.onAfterRender = entry.after;
        entry.depth.material.dispose();
      }
      entries.length = 0;
    },
  };
}
