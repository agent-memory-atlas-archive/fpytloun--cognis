import { createPinnedPanel, type PinnedPanel } from './pinned-panel.svelte';

export function pinnedPanelTestState(onClose: () => void) {
  let panel!: PinnedPanel;
  const destroy = $effect.root(() => {
    panel = createPinnedPanel({ visible: () => false, projectId: () => null, onClose });
  });
  return { panel, destroy };
}
