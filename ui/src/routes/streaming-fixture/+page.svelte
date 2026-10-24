<script lang="ts">
  import { dev } from '$app/environment';
  import { onMount } from 'svelte';
  import ChatV2TimelineList from '$lib/components/chat-v2/ChatV2TimelineList.svelte';
  import { DEFAULT_USER_PREFERENCES } from '$lib/user-preferences';
  import type { ChatRealtimeFrame, ChatSnapshot, RuntimeOverlaySnapshot, TimelineItem } from '$lib/chat-v2/types';
  import { ChatV2Store } from '$lib/chat-v2/store.svelte';

  let items = $state<TimelineItem[]>([]);
  let runtime = $state<RuntimeOverlaySnapshot | null>(null);
  let framed = $state(false);
  const store = new ChatV2Store();
  let preferences = $state({
    ...DEFAULT_USER_PREFERENCES,
    chat: { ...DEFAULT_USER_PREFERENCES.chat, group_tool_calls: true },
  });

  onMount(() => {
    if (!dev) return;
    const host = window as typeof window & {
      streamingFixture?: (next: TimelineItem[], overlay: RuntimeOverlaySnapshot | null) => void;
      streamingSnapshot?: (snapshot: ChatSnapshot) => void;
      streamingFrame?: (frame: ChatRealtimeFrame) => void;
      streamingGroups?: (enabled: boolean) => void;
    };
    host.streamingFixture = (next, overlay) => { framed = false; items = next; runtime = overlay; };
    host.streamingSnapshot = snapshot => { store.replaceFromSnapshot(snapshot); framed = true; };
    host.streamingFrame = frame => { store.applyRealtime(frame); };
    host.streamingGroups = enabled => { preferences.chat.keep_assistant_messages_separate = !enabled; };
    return () => { delete host.streamingFixture; delete host.streamingSnapshot; delete host.streamingFrame; delete host.streamingGroups; };
  });
</script>

{#if dev}
  <main class="min-h-screen bg-slate-950 p-6 text-slate-100">
    <div class="mx-auto max-w-3xl" data-testid="streaming-fixture">
      <ChatV2TimelineList items={framed ? store.visibleItems : items}
        runtime={framed ? store.snapshot.runtime : runtime}
        cycleStates={(framed ? store.snapshot.runtime : runtime)?.cycle_states ?? []} {preferences} />
    </div>
  </main>
{/if}
