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
  toggle.addEventListener('change', () => receiver.reset());
  document.addEventListener('visibilitychange', () => receiver.reset());
  window.addEventListener('pagehide', () => receiver.reset());

  async function poll() {
    let delay = 1000;
    try {
      if (document.hidden) { receiver.reset(); return; }
      const response = await fetch('/api/gestures/state', { cache: 'no-store', signal: AbortSignal.timeout(1500) });
      if (!response.ok) throw new Error('Gestenverbindung unterbrochen');
      const state = await response.json();
      if (toggle.checked) receiver.accept(state);
      else receiver.reset();
      if (state.status === 'error') label.textContent = `Kamera nicht verfügbar: ${state.error}`;
      else if (state.status === 'disabled') label.textContent = 'Gestenerkennung ist beim Serverstart ausgeschaltet.';
      else if (!state.connected) label.textContent = 'Warte auf die Kamera …';
      else if (!toggle.checked) label.textContent = 'Gestensteuerung für diese Ansicht pausiert.';
      else label.textContent = state.holding ? 'Gegriffen · Hand bewegen zum Drehen' : state.idle ? 'Bereit · Sparmodus (3 Bilder/s)' : 'Bereit · Daumen und Zeigefinger zusammenführen';
      delay = state.connected ? (state.idle ? 333 : 50) : 1000;
    } catch (error) {
      receiver.reset();
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
