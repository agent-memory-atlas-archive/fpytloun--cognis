<script lang="ts">
  // Test-only route: copied into routes only during the isolated WK export.
  import '$lib/native/workspace-acceptance-trace';
  import { conversationWorkspace } from '$lib/dashboard/conversation-workspace';
  import { pinnedConversations } from '$lib/dashboard/conversation-workspace-runtime';
  import { auth } from '$lib/stores/auth';
  import { page } from '$app/stores';
  import PinnedConversationDock from '$lib/components/chat/PinnedConversationDock.svelte';
  import type { WorkspaceIntent } from '$lib/dashboard/conversation-workspace';
  import { onMount } from 'svelte';
  import { nativeConfiguration } from '$lib/native/host';
  import { WorkspaceManager } from '$lib/dashboard/workspace';
  const manager = new WorkspaceManager('desktop', { x: 0, y: 0, width: 1440, height: 900 });
  let windows = $state(manager.snapshot());
  let bindingResult = $state('');
  let validationGate = $state('idle');
  let releaseValidation: (() => void) | undefined;
  let unbind: (() => void) | undefined;
  const isMain = nativeConfiguration()?.surface === 'main';
  function bind(project: string | null = null) {
    unbind?.();
    unbind = conversationWorkspace.bind(manager, project, 'workspace-native-acceptance-empty');
  }
  onMount(() => {
    if (isMain) bind();
    const stop = manager.subscribe(() => { windows = manager.snapshot(); });
    return () => { releaseValidation?.(); unbind?.(); stop(); };
  });
  async function seedBinding() {
    if (!isMain) throw new Error('Only main owns a binding');
    for (let i = 0; i < 9; i++) {
      const value = await conversationWorkspace.execute({ type: 'pin', conversationId: `conv_capacity_${i}`, select: false });
      if (!value.ok) throw new Error(JSON.stringify(value));
    }
    const opened = await conversationWorkspace.execute({
      type: 'open-agent', agentId: 'agent_first', title: 'Resolved agent', projectId: null,
    });
    if (!opened.ok) throw new Error(JSON.stringify(opened));
    await conversationWorkspace.resolveAgent('agent:agent_first', {
      conversation_id: 'conv_second', agent_id: 'agent_first', project_id: null, title: 'Second',
    } as Parameters<typeof conversationWorkspace.resolveAgent>[1]);
    manager.minimize('conversation:conv_capacity_0');
    bindingResult = 'seeded';
  }
  async function openBinding(id = 'conv_second') {
    bindingResult = 'pending';
    bindingResult = JSON.stringify(await manager.requestOpen({
      kind: 'conversation', entityId: id, title: id, canonicalHref: `/chat/${id}`,
    }));
  }
  // A real IDB writer blocks the production lease's readwrite transaction.
  // No lease callback, bridge handler, or production field is replaced.
  async function holdValidation() {
    if (releaseValidation) throw new Error('Validation gate already held');
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('cognis-profile-intent-v1', 1);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    const tx = db.transaction('profiles', 'readwrite');
    const store = tx.objectStore('profiles');
    let held = true;
    releaseValidation = () => { held = false; releaseValidation = undefined; };
    tx.oncomplete = tx.onabort = () => { db.close(); validationGate = 'released'; };
    function keepAlive() {
      const request = store.get(location.origin);
      request.onsuccess = () => {
        validationGate = 'held';
        if (held) keepAlive();
      };
    }
    keepAlive();
  }
  let result = $state('');
  async function command(intent: WorkspaceIntent) {
    result = 'pending';
    result = JSON.stringify(await conversationWorkspace.execute(intent));
  }
</script>
{#if $page.url.searchParams.get('rail') === 'browser'}
  <PinnedConversationDock />
{/if}
<output id="workspace-state">{JSON.stringify($conversationWorkspace)}</output>
<output id="workspace-summaries">{JSON.stringify(Object.keys($pinnedConversations))}</output>
<output id="workspace-result">{result}</output>
<output id="auth-state">{$auth.status}</output>
<button id="pin-first" onclick={() => command({ type: 'pin', conversationId: 'conv_first', select: true })}>Pin first</button>
<button id="pin-second" onclick={() => command({ type: 'pin', conversationId: 'conv_second', select: true })}>Pin second</button>
<button id="unpin-first" onclick={() => command({ type: 'unpin', key: 'conversation:conv_first' })}>Unpin first</button>
<button id="select-first" onclick={() => command({ type: 'select', agentId: 'agent_first', key: 'conversation:conv_first' })}>Select first</button>
<button id="logout" onclick={() => auth.logout()}>Logout</button>
{#if isMain}
  <output id="binding-windows">{JSON.stringify(windows)}</output>
  <output id="binding-result">{bindingResult}</output>
  <output id="validation-gate">{validationGate}</output>
  <button id="binding-seed" onclick={seedBinding}>Seed ten retained and four visible</button>
  <button id="binding-open" onclick={() => openBinding()}>Restore resolved identity</button>
  <button id="binding-new" onclick={() => openBinding('conv_fresh')}>Open new identity</button>
  <button id="binding-forbidden" onclick={() => openBinding('conv_forbidden')}>Open rejected identity</button>
  <button id="binding-hold" onclick={holdValidation}>Hold owner validation</button>
  <button id="binding-release" onclick={() => releaseValidation?.()}>Release owner validation</button>
  <button id="binding-minimize" onclick={() => manager.minimize('agent:agent_first')}>Minimize target</button>
  <button id="binding-dispose" onclick={() => { unbind?.(); unbind = undefined; }}>Dispose binding</button>
  <button id="binding-project" onclick={() => bind('project_other')}>Rebind project</button>
  <button id="binding-dashboard" onclick={() => bind()}>Rebind dashboard</button>
{/if}
