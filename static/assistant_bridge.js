import { initAssistant } from './assistant.js';

let activeViewer = null;

const emptyState = () => ({
  loaded: [],
  visible: [],
  highlighted: [],
  opacities: {},
  cuts: { x: [0, 100], y: [0, 100], z: [0, 100] },
});

const bridge = {
  getState() {
    return activeViewer ? activeViewer.getState() : emptyState();
  },
  execute(action) {
    if (!activeViewer) {
      throw new Error('Die 3D-Ansicht ist noch nicht bereit; die Textantwort bleibt verfügbar.');
    }
    return activeViewer.execute(action);
  },
  describe(action) {
    return activeViewer ? activeViewer.describe(action) : '3D-Aktion noch nicht verfügbar.';
  },
  glowRegions(ids) { activeViewer?.glowRegions(ids); },
  clearMentionGlow() { activeViewer?.clearMentionGlow(); },
};

export function attachViewer(viewer) {
  activeViewer = viewer;
}

initAssistant(bridge);
