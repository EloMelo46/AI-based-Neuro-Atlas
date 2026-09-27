import * as THREE from 'three';

export const ROTATION_SENSITIVITY = 1.0;

// Change the orbit directly, retaining target, zoom and anatomical cut planes.
export function rotateView(camera, controls, dx, dy) {
  const up = new THREE.Quaternion().setFromUnitVectors(camera.up.clone().normalize(), new THREE.Vector3(0, 1, 0));
  const offset = camera.position.clone().sub(controls.target).applyQuaternion(up);
  const spherical = new THREE.Spherical().setFromVector3(offset);
  spherical.theta -= dx * 2 * Math.PI * ROTATION_SENSITIVITY;
  spherical.phi -= dy * 2 * Math.PI * ROTATION_SENSITIVITY;
  spherical.theta = THREE.MathUtils.clamp(spherical.theta, controls.minAzimuthAngle, controls.maxAzimuthAngle);
  spherical.phi = THREE.MathUtils.clamp(spherical.phi, controls.minPolarAngle, controls.maxPolarAngle);
  spherical.makeSafe();
  offset.setFromSpherical(spherical).applyQuaternion(up.invert());
  camera.position.copy(controls.target).add(offset);
  controls.update();
}

// Separate from transport so reloads, dropped packets and release can be tested.
export function createGestureReceiver({ start, move, end }) {
  let previous = null;
  let holding = false;
  function finish() {
    if (holding) end();
    holding = false;
  }
  return {
    reset() { finish(); previous = null; },
    accept(state) {
      if (!state.connected || !Number.isFinite(state.x) || !Number.isFinite(state.y)) {
        this.reset();
        return;
      }
      // First state after load/reconnect is a baseline, never replay old movement.
      if (!previous || previous.session !== state.session) {
        finish();
        previous = state;
        return;
      }
      const newGrab = previous.grab_id !== state.grab_id;
      if (newGrab) finish();
      const dx = state.x - (newGrab ? 0 : previous.x);
      const dy = state.y - (newGrab ? 0 : previous.y);
      if (state.holding || previous.holding || newGrab) {
        if (!holding && (state.holding || dx || dy)) { start(); holding = true; }
        if (holding && (dx || dy)) move(dx, dy);
      }
      if (!state.holding) finish();
      previous = state;
    },
  };
}

// Require a neutral pose after page load/reconnect; never replay an old hold.
export function createListenReceiver({ start, end, cancel }) {
  let session = null;
  let armed = false;
  let active = false;
  let listenId = null;
  return {
    reset() {
      if (active) cancel();
      active = false;
      armed = false;
      session = null;
      listenId = null;
    },
    accept(state) {
      if (!state.connected) { this.reset(); return; }
      if (session !== state.session) {
        this.reset();
        session = state.session;
        armed = !state.listening;
        return;
      }
      if (active && state.listening && state.listen_id !== listenId) {
        // A release and a new hold happened between polls: discard the old audio.
        cancel();
        active = false;
      }
      if (!state.listening || state.holding) {
        if (active) end();
        active = false;
        armed = true;
      } else if (armed && !active) {
        active = true;
        listenId = state.listen_id;
        start();
      }
    },
  };
}

export function attachGestureControl({ camera, controls, requestRender, onGrab, onRelease }) {
  const label = document.getElementById('gesture-status');
  const toggle = document.getElementById('gesture-enabled');
  const preview = document.getElementById('gesture-preview');
  const image = document.getElementById('gesture-image');
  let enabledBeforeGrab = true;
  const receiver = createGestureReceiver({
    start() {
      // Drain outstanding mouse damping before taking over the same camera.
      const damping = controls.enableDamping;
      controls.enableDamping = false;
      controls.update();
      controls.enableDamping = damping;
      enabledBeforeGrab = controls.enabled;
      controls.enabled = false;
      onGrab();
    },
    move(dx, dy) { rotateView(camera, controls, dx, dy); requestRender(); },
    end() {
      controls.enabled = enabledBeforeGrab;
      onRelease();
      requestRender();
    },
  });
  const notifyListen = (active, cancel = false) => document.dispatchEvent(
    new CustomEvent('gesture-listen', { detail: { active, cancel } }));
  const listenReceiver = createListenReceiver({
    start: () => notifyListen(true), end: () => notifyListen(false),
    cancel: () => notifyListen(false, true),
  });
  function reset() { receiver.reset(); listenReceiver.reset(); }
  toggle.addEventListener('change', reset);
  document.addEventListener('visibilitychange', reset);
  window.addEventListener('pagehide', reset);

  async function poll() {
    let delay = 1000;
    try {
      if (document.hidden) { reset(); return; }
      const response = await fetch('/api/gestures/state', { cache: 'no-store', signal: AbortSignal.timeout(1500) });
      if (!response.ok) throw new Error('Gestenverbindung unterbrochen');
      const state = await response.json();
      if (toggle.checked && !document.hidden) { receiver.accept(state); listenReceiver.accept(state); }
      else reset();
      if (state.status === 'error') label.textContent = `Kamera nicht verfügbar: ${state.error}`;
      else if (state.status === 'disabled') label.textContent = 'Gestenerkennung ist beim Serverstart ausgeschaltet.';
      else if (!state.connected) label.textContent = 'Warte auf die Kamera …';
      else if (!toggle.checked) label.textContent = 'Gestensteuerung für diese Ansicht pausiert.';
      else label.textContent = state.listening ? 'Sprechgeste aktiv · Finger senken zum Senden' : state.holding ? 'Gegriffen · Hand bewegen zum Drehen' : state.idle ? 'Bereit · Sparmodus (3 Bilder/s)' : 'Bereit · Greifen zum Drehen / Zeigefinger hoch zum Sprechen';
      delay = state.connected ? (state.idle ? 333 : 50) : 1000;
    } catch (error) {
      reset();
      label.textContent = 'Verbindung zur Gestenerkennung unterbrochen.';
    } finally { window.setTimeout(poll, delay); }
  }
  async function previewFrame() {
    try {
      if (!preview.open || document.hidden) return;
      const response = await fetch('/api/gestures/preview', { cache: 'no-store', signal: AbortSignal.timeout(1500) });
      if (response.status !== 200) return;
      const old = image.src;
      image.src = URL.createObjectURL(await response.blob());
      if (old.startsWith('blob:')) URL.revokeObjectURL(old);
    } catch { /* Status is reported by the state request. */ }
    finally { window.setTimeout(previewFrame, 200); }
  }
  poll();
  previewFrame();
  return receiver;
}
