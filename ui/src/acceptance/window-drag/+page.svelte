<script lang="ts">
  import { onDestroy } from 'svelte';
  import { auth } from '$lib/stores/auth';
  import { isNativeHost, nativeConfiguration } from '$lib/native/host';
  import { conversationWorkspace } from '$lib/dashboard/conversation-workspace';
  import { WorkspaceManager, serializeWorkspaceWindows } from '$lib/dashboard/workspace';
  import WorkspaceLayer from '$lib/components/dashboard/WorkspaceLayer.svelte';

  const manager = new WorkspaceManager('desktop', { x: 12, y: 120, width: 1500, height: 820 });
  const storageKey = 'native-drag-acceptance-layout';
  let seeded = $state(false);
  let failure = $state('');
  let output = $state('{}');
  let initialLoaded = $state<string[]>([]);
  const summaryReady = $derived($manager.length > 0 && $manager.every((item) =>
    item.title === `Synthetic ${item.entityId}` && item.status === 'active'));
  let publications = 0;
  let derivedWrites = 0;
  let baseline: Record<string, number> = {};
  let stops: Array<() => void> = [];
  let saved: {
    panels: HTMLElement[]; viewports: HTMLElement[]; composers: HTMLTextAreaElement[];
    scroll: number[]; detail: HTMLElement; focus: Element | null;
  } | null = null;
  const services = () => (window as unknown as Window & {
    nativeDragServices: { writes: () => Record<string, number> };
  }).nativeDragServices;

  async function seed() {
    try {
      if (!isNativeHost() || nativeConfiguration()?.surface !== 'main') throw Error('Actual native main required');
      const count = Number(new URLSearchParams(location.search).get('windows'));
      if (count !== 1 && count !== 5) throw Error('Expected one or five fixture chats');
      for (let index = 0; index < count; index++) {
        const result = await conversationWorkspace.execute({
          type: 'pin', conversationId: `drag-chat-${index}`, select: true,
        });
        if (!result.ok) throw Error('Canonical owner rejected fixture pin');
      }
      stops.push(conversationWorkspace.bind(manager, null, storageKey));
      stops.push(manager.subscribe(() => {
        publications++;
        // Mirror ControlCenter's durable-layout consumer. Count attempted writes
        // separately from the physical Storage.setItem observations.
        derivedWrites++;
        localStorage.setItem(storageKey, serializeWorkspaceWindows(manager.persistentSnapshot()));
      }));
      seeded = true;
    } catch (error) { failure = String(error); }
  }
  function prepare() {
    const panels = [...document.querySelectorAll<HTMLElement>('[data-window-key]')];
    const viewports = panels.map((panel) => panel.querySelector<HTMLElement>('[data-testid="scoped-timeline-viewport"]')!);
    const composers = panels.map((panel, index) => {
      const input = panel.querySelector<HTMLTextAreaElement>('textarea')!;
      input.value = `Native preserved draft ${index}`;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      return input;
    });
    const detail = panels[panels.length - 1].querySelector<HTMLElement>('button[aria-controls^="tool-call-content-"]')!;
    if (!detail || detail.getAttribute('aria-expanded') !== 'true') throw Error('Open actual tool disclosure first');
    composers[composers.length - 1].focus();
    composers[composers.length - 1].setSelectionRange(2, 7);
    viewports.forEach((node) => { node.scrollTop = Math.floor((node.scrollHeight - node.clientHeight) / 2); });
    if (document.activeElement !== composers[composers.length - 1]) throw Error('Composer focus not established');
    if (viewports.some((node) => node.scrollTop <= 0 || node.scrollTop >= node.scrollHeight - node.clientHeight)) {
      throw Error('Non-bottom, nonzero scroll baseline required');
    }
    saved = { panels, viewports, composers, detail, scroll: viewports.map((node) => node.scrollTop), focus: document.activeElement };
    observe();
  }
  function reset() {
    publications = 0;
    derivedWrites = 0;
    baseline = services().writes();
    observe();
  }
  function observe() {
    const physical = Object.entries(services().writes()).filter(([key]) =>
      key === storageKey || key.startsWith('cognis.conversation-workspace.'));
    const writes = physical.reduce((total, [key, value]) => total + value - (baseline[key] ?? 0), 0);
    output = JSON.stringify({
      native: isNativeHost(), surface: nativeConfiguration()?.surface,
      publications, derivedLayoutWriteAttempts: derivedWrites, physicalWorkspaceWrites: writes,
      readyRows: [...document.querySelectorAll('[data-kind="message"]')].filter((node) =>
        node.textContent?.includes('Synthetic message 119')).length,
      geometry: manager.snapshot().map((item) => ({ key: item.key, rect: item.rect })),
      initialLoaded, summaryReady,
      dock: document.querySelector('[data-testid="workspace-dock"]') !== null,
      visual: saved ? (() => {
        const rect = saved!.panels[saved!.panels.length - 1].getBoundingClientRect();
        return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
      })() : null,
      stream: document.body.textContent?.match(/Native streaming token (\d+)/)?.[1] ?? null,
      preserved: saved ? {
        viewport: saved.viewports.every((node, index) => node.isConnected
          && saved!.panels[index].querySelector('[data-testid="scoped-timeline-viewport"]') === node),
        expanded: saved.detail.isConnected && saved.detail.getAttribute('aria-expanded') === 'true',
        draft: saved.composers.every((node, index) => node.isConnected && node.value === `Native preserved draft ${index}`),
        selection: [saved.composers[saved.composers.length - 1].selectionStart, saved.composers[saved.composers.length - 1].selectionEnd],
        focus: document.activeElement === saved.focus,
        scroll: saved.viewports.every((node, index) => node.scrollTop === saved!.scroll[index]),
      } : null,
    });
  }
  onDestroy(() => { for (const stop of stops.reverse()) stop(); });
</script>

<div class="fixed left-0 top-0 z-[200]">
  <output id="native-drag-bootstrap">{JSON.stringify({
    auth: $auth.status, owner: $conversationWorkspace.owner, seeded, failure,
    initialLoaded, summaryReady,
    native: isNativeHost(), surface: nativeConfiguration()?.surface,
  })}</output>
  <button id="native-drag-seed" onclick={seed}>Seed synthetic workspace</button>
  <button id="native-drag-prepare" onclick={prepare}>Capture public DOM invariants</button>
  <button id="native-drag-reset" onclick={reset}>Reset measured gesture counters</button>
  <button id="native-drag-observe" onclick={observe}>Observe typed snapshot</button>
  <output id="native-drag-snapshot">{output}</output>
</div>
{#if seeded}
  <WorkspaceLayer
    {manager}
    onConversationInitialLoaded={(id) => {
      if (!initialLoaded.includes(id)) initialLoaded = [...initialLoaded, id];
    }}
  />
{/if}
