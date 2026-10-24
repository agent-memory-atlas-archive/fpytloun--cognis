<script lang="ts">
  import { onMount } from 'svelte';
  import WorkspaceWindow from '../../src/lib/components/dashboard/WorkspaceWindow.svelte';
  import CompactConversationChat from '../../src/lib/components/chat-v2/CompactConversationChat.svelte';
  import { WorkspaceManager, serializeWorkspaceWindows } from '../../src/lib/dashboard/workspace';
  import { ConversationWorkspace } from '../../src/lib/dashboard/conversation-workspace';
  import { conversationTimelineScope } from '../../src/lib/chat-v2/types';

  const count = Number(new URLSearchParams(location.search).get('windows') ?? 1);
  const originalScopePath = new URLSearchParams(location.search).get('scope') === 'original';
  const scopes = new Map(Array.from({ length: count }, (_, index) => {
    const scope = conversationTimelineScope(`drag-chat-${index}`);
    return [scope.key, scope] as const;
  }));
  const manager = new WorkspaceManager('desktop', { x: 12, y: 12, width: 1500, height: 940 });
  const retained = new ConversationWorkspace();
  const counters = { publications: 0, retainedPublications: 0, writes: 0, json: 0 };
  onMount(() => {
    retained.setOwner('drag-acceptance@cognis.test', localStorage);
    for (let index = 0; index < count; index += 1) {
      manager.open({
        kind: 'conversation', entityId: `drag-chat-${index}`, title: `Synthetic chat ${index}`,
        canonicalHref: `/chat/drag-chat-${index}`,
      });
    }
    localStorage.setItem('drag-acceptance-legacy', serializeWorkspaceWindows(manager.snapshot()));
    void retained.reduce({ type: 'migrate', key: 'drag-acceptance-legacy', projectId: null });
    // Exercise the real retained-layout and dashboard persistence consumers.
    const stopBind = retained.bind(manager, null, 'drag-acceptance-legacy');
    const stopRetained = retained.subscribe(() => counters.retainedPublications++);
    const stopManager = manager.subscribe(() => {
      counters.publications++;
      localStorage.setItem('drag-acceptance-legacy', serializeWorkspaceWindows(manager.persistentSnapshot()));
    });
    const originalSetItem = Storage.prototype.setItem;
    const originalStringify = JSON.stringify;
    Storage.prototype.setItem = function(key, value) {
      counters.writes++;
      return originalSetItem.call(this, key, value);
    };
    JSON.stringify = function(...args: Parameters<typeof JSON.stringify>) {
      counters.json++;
      return originalStringify(...args);
    } as typeof JSON.stringify;
    Object.assign(window, {
      dragAcceptance: {
        reset: () => { for (const key of Object.keys(counters) as Array<keyof typeof counters>) counters[key] = 0; },
        counts: () => ({ ...counters }),
        snapshot: () => manager.snapshot(),
      },
    });
    return () => {
      Storage.prototype.setItem = originalSetItem;
      JSON.stringify = originalStringify;
      stopManager(); stopRetained(); stopBind();
    };
  });
</script>

{#each $manager as windowState (windowState.key)}
  {@const scope = scopes.get(windowState.key)!}
  <WorkspaceWindow window={windowState} {manager}>
    {#if originalScopePath}
      <!-- Preserve the original failing prop path for the sync owner's regression. -->
      <CompactConversationChat conversationId={windowState.entityId} embedded />
    {:else}
      <CompactConversationChat conversationId={scope.conversation_id!} timelineScope={scope} embedded />
    {/if}
  </WorkspaceWindow>
{/each}
