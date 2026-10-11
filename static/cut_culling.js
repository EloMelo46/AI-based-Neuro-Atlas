// The anatomical meshes stay fixed in world space; only the camera and cutting
// planes move. Cache their transformed bounds once and skip GPU work for a
// surface wholly outside any retained half-space. Intersecting bounds remain
// visible, including a small margin for GPU floating-point plane calculations.
export function createCutCulling(THREE, brain) {
  brain.updateMatrixWorld(true);
  const entries = [];
  brain.traverse(surface => {
    if (!surface.isMesh) return;
    if (!surface.geometry.boundingBox) surface.geometry.computeBoundingBox();
    entries.push({
      surface,
      bounds: surface.geometry.boundingBox.clone().applyMatrix4(surface.matrixWorld),
      originallyVisible: surface.visible,
    });
  });
  const paddingMm = 0.0001;
  return {
    update(planes) {
      for (const { surface, bounds, originallyVisible } of entries) {
        const outside = !bounds.isEmpty() && planes.some(plane => {
          const { x, y, z } = plane.normal;
          const farthestDistance = x * (x >= 0 ? bounds.max.x : bounds.min.x)
            + y * (y >= 0 ? bounds.max.y : bounds.min.y)
            + z * (z >= 0 ? bounds.max.z : bounds.min.z) + plane.constant;
          return farthestDistance < -paddingMm;
        });
        surface.userData.cutCulled = outside;
        // Region selection belongs to the parent wrapper, not this render hint.
        surface.visible = originallyVisible && !outside;
      }
    },
    getDiagnostics() {
      return {
        surfaces: entries.length,
        culledSurfaces: entries.filter(({ surface }) => surface.userData.cutCulled).length,
      };
    },
  };
}
