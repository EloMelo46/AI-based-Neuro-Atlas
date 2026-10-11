// Winding-count stencil sections of validated closed solids. Helper meshes
// share the original quantized GPU buffers: no tessellation or mesh copies.
export function createCutCaps(THREE, scene, brain, planes) {
  brain.updateMatrixWorld(true);
  const entries = [];
  const capGeometry = new THREE.PlaneGeometry(1, 1);
  const surfaces = [];
  brain.traverse(surface => {
    // Only audited closed oriented triangle chains can produce a winding fill.
    if (surface.isMesh && surface.userData.cutEligible === true) surfaces.push(surface);
  });
  const boundsFor = surface => {
    if (!surface.geometry.boundingBox) surface.geometry.computeBoundingBox();
    return surface.geometry.boundingBox.clone().applyMatrix4(surface.matrixWorld);
  };
  // Quantized attributes use different node scales per region. Compare actual
  // world bounds when drawing overlapping labels, never quantized coordinates.
  const bounded = surfaces.map(surface => ({ surface, bounds: boundsFor(surface) }));
  const volume = bounds => {
    const size = bounds.getSize(new THREE.Vector3());
    return size.x * size.y * size.z;
  };
  // Residual fills and CSF are background coverage. Named anatomy takes
  // priority where independently smoothed meshes overlap in the section.
  bounded.sort((a, b) => (a.surface.userData.cutPriority ?? 0) - (b.surface.userData.cutPriority ?? 0)
    || volume(b.bounds) - volume(a.bounds));
  bounded.forEach(({ surface, bounds }, regionIndex) => {
    planes.forEach((plane, planeIndex) => {
      entries.push({ surface, bounds, plane, regionIndex,
        center: bounds.getCenter(new THREE.Vector3()),
        size: bounds.getSize(new THREE.Vector3()).length() * 1.05,
        order: 1 + (regionIndex * planes.length + planeIndex) * 3,
        group: null, cap: null });
    });
  });

  function initialize(entry) {
    const { surface, plane, order, regionIndex } = entry;
    const group = new THREE.Group();
    const base = {
      depthWrite: false, depthTest: false, colorWrite: false,
      stencilWrite: true, stencilFunc: THREE.AlwaysStencilFunc,
      clippingPlanes: [plane],
    };
    const decrement = THREE.DecrementWrapStencilOp;
    const stencilMaterial = new THREE.MeshBasicMaterial({ ...base,
      side: THREE.DoubleSide, forceSinglePass: true,
      stencilFail: decrement, stencilZFail: decrement, stencilZPass: decrement });
    const stencil = new THREE.Mesh(surface.geometry, stencilMaterial);
    stencil.matrixAutoUpdate = false;
    stencil.matrix.copy(surface.matrixWorld);
    stencil.renderOrder = order;
    stencil.frustumCulled = false;
    // r152 sets the same operations for both faces. Prime that cached state
    // before overriding the back face: setMaterial then leaves it intact.
    // Signed winding is unchanged, but vertices are transformed only once.
    stencil.onBeforeRender = renderer => {
      const gl = renderer.getContext();
      renderer.state.buffers.stencil.setOp(decrement, decrement, decrement);
      gl.stencilOpSeparate(gl.BACK, gl.INCR_WRAP, gl.INCR_WRAP, gl.INCR_WRAP);
    };
    stencil.onAfterRender = renderer => {
      // Restore the actual GL state to match Three's cache before any other
      // surface/cap draw, including transparent queues and later frames.
      renderer.getContext().stencilOp(decrement, decrement, decrement);
    };
    group.add(stencil);
    const material = new THREE.MeshBasicMaterial({
      color: surface.material.color, side: THREE.DoubleSide,
      forceSinglePass: true,
      clippingPlanes: planes.filter(other => other !== plane),
      stencilWrite: true, stencilRef: 0, stencilFunc: THREE.NotEqualStencilFunc,
      stencilFail: THREE.ReplaceStencilOp, stencilZFail: THREE.ReplaceStencilOp,
      stencilZPass: THREE.ReplaceStencilOp,
      polygonOffset: true, polygonOffsetFactor: 0, polygonOffsetUnits: -(regionIndex + 1) * 2,
    });
    const cap = new THREE.Mesh(capGeometry, material);
    cap.scale.setScalar(entry.size);
    cap.renderOrder = order + 2;
    cap.frustumCulled = false;
    cap.onAfterRender = renderer => renderer.clearStencil();
    group.add(cap);
    scene.add(group);
    entry.group = group;
    entry.cap = cap;
  }

  const forward = new THREE.Vector3(0, 0, 1);
  const extent = new THREE.Vector3();
  const frustum = new THREE.Frustum();
  const viewProjection = new THREE.Matrix4();
  let hiddenByView = 0;
  function remainsInSlab(entry) {
    entry.bounds.getSize(extent).multiplyScalar(0.5);
    return planes.every(plane => plane.distanceToPoint(entry.center)
      + Math.abs(plane.normal.x) * extent.x + Math.abs(plane.normal.y) * extent.y
      + Math.abs(plane.normal.z) * extent.z >= 0);
  }
  return {
    update(enabled, camera = null) {
      hiddenByView = 0;
      if (camera) {
        camera.updateMatrixWorld();
        frustum.setFromProjectionMatrix(viewProjection.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse));
      }
      for (const entry of entries) {
        const surfaceMaterial = entry.surface.material;
        const opacity = surfaceMaterial.opacity * (surfaceMaterial.userData.cutOpacityScale ?? 1);
        let visible = enabled && opacity > 0;
        for (let node = entry.surface; node && visible; node = node.parent) visible = node.visible;
        visible = visible && entry.bounds.intersectsPlane(entry.plane) && remainsInSlab(entry);
        if (visible && camera) {
          // Keep both cap sides: thin/overlapping labels and the depth bias
          // used to distinguish their sections can make either side visible.
          if (!frustum.intersectsBox(entry.bounds)) {
            visible = false;
            hiddenByView++;
          }
        }
        if (!visible) {
          if (entry.group) entry.group.visible = false;
          continue;
        }
        // Allocate only on the first intersecting cut. Keep these tiny objects
        // cached when sliding a plane to avoid allocation/GC during gestures.
        if (!entry.group) initialize(entry);
        entry.group.visible = true;
        entry.cap.material.color.copy(surfaceMaterial.userData.cutColor ?? surfaceMaterial.color);
        const transparent = opacity < 1;
        // The stencil draw and its cap must remain in the same render queue.
        for (const child of entry.group.children) {
          if (child.material.transparent !== transparent) child.material.needsUpdate = true;
          child.material.transparent = transparent;
        }
        entry.cap.material.opacity = opacity;
        entry.cap.material.depthWrite = !transparent;
        entry.plane.projectPoint(entry.center, entry.cap.position);
        entry.cap.quaternion.setFromUnitVectors(forward, entry.plane.normal);
      }
    },
    getDiagnostics() {
      return {
        eligibleSurfaces: surfaces.length,
        allocatedSections: entries.filter(entry => entry.group).length,
        visibleSections: entries.filter(entry => entry.group?.visible).length,
        viewCulledSections: hiddenByView,
        stencilPassesPerSection: 1,
        sharedSurfaceBuffers: entries.every(entry => !entry.group
          || entry.group.children[0].geometry === entry.surface.geometry),
      };
    },
    dispose() {
      for (const entry of entries) {
        if (!entry.group) continue;
        entry.group.removeFromParent();
        for (const child of entry.group.children) child.material.dispose();
      }
      // The anatomical surface buffers belong to the viewer, not the helpers.
      capGeometry.dispose();
      entries.length = 0;
    },
  };
}
