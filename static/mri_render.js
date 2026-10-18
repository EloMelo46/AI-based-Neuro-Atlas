// NiiVue 0.64 issues several synchronous draws per input event. Keep its renderer
// intact, but submit the latest state at most once per animation frame.
export function scheduleMRIRendering(nv, isVisible) {
  const draw = nv.drawScene.bind(nv);
  const drawVolume = nv.drawImage3D.bind(nv);
  let frame = 0, preview = false, lastResult;
  const waiters = [];
  // The pinned NiiVue 0.64 shader derives ray steps from texVox. Use a coarse
  // 3D preview during a grab; keep the native 2D textures and canvas unchanged.
  // Restore the uniform immediately, including when a draw throws. Picking
  // always uses the original resolution and its own shader.
  nv.drawImage3D = (...args) => {
    if (!preview || !nv.back || nv.uiData.mouseDepthPicker) return drawVolume(...args);
    const shader = nv.renderShader;
    const vox = nv.sliceScale(true).vox;
    shader.use(nv.gl);
    nv.gl.uniform3fv(shader.uniforms.texVox, vox.map(value => value * 0.25));
    try { return drawVolume(...args); }
    finally { shader.use(nv.gl); nv.gl.uniform3fv(shader.uniforms.texVox, vox); }
  };
  function render() {
    frame = 0;
    const callbacks = waiters.splice(0);
    try {
      if (isVisible() && !document.hidden) {
        lastResult = draw();
      }
      callbacks.forEach(({ resolve }) => resolve());
    } catch (error) {
      callbacks.forEach(({ reject }) => reject(error));
      if (!callbacks.length) throw error;
    }
  }
  function request() {
    if (!frame && isVisible() && !document.hidden) frame = requestAnimationFrame(render);
    return lastResult;
  }
  nv.drawScene = request;
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) cancel(); else request();
  });
  function cancel() {
    cancelAnimationFrame(frame);
    frame = 0;
    waiters.splice(0).forEach(({ resolve }) => resolve());
  }
  return {
    request,
    cancel,
    isPreview: () => preview,
    setInteractive(value) {
      if (preview === value) return;
      preview = value;
      request();
    },
    flush() {
      if (!frame) return Promise.resolve();
      return new Promise((resolve, reject) => waiters.push({ resolve, reject }));
    },
  };
}
