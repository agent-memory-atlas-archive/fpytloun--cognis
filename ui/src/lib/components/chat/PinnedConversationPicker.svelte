<script lang="ts">
  import { findTarget } from '$lib/find';
  import { tick } from 'svelte';
  import Star from 'lucide-svelte/icons/star';
  import Search from 'lucide-svelte/icons/search';
  import { api, asApiError } from '$lib/api/client';
  import type { Agent, Conversation } from '$lib/types/api';
  import { isTaskControlConversationSummary } from '$lib/chat-page';
  import { conversationActivityState } from '$lib/conversation-activity';
  import { pinnedBackgroundWork, pinnedConversations } from '$lib/dashboard/conversation-workspace-runtime';
  import { conversationWorkspace } from '$lib/dashboard/conversation-workspace';
  import ActivityAvatar from '$lib/components/ActivityAvatar.svelte';
  import TodoProgressPopover from '$lib/components/TodoProgressPopover.svelte';
  import { useSectionConnectivity } from '$lib/connectivity-section.svelte';

  let { agentId, agent, onOpen } = $props<{
    agentId: string; agent?: Agent; onOpen: (conversation: Conversation) => void | Promise<void>;
  }>();
  let query = $state('');
  let input = $state<HTMLInputElement | null>(null);
  let rows = $state<Conversation[]>([]);
  let cursor = $state<string | null>(null);
  let loading = $state(false);
  let error = $state('');
  let generation = 0;
  let controller: AbortController | null = null;
  const owner = $derived($conversationWorkspace.owner);
  const net = useSectionConnectivity({ hasError: () => Boolean(error), retry: () => load() });
  async function load(append = false): Promise<void> {
    controller?.abort(); controller = new AbortController();
    const request = ++generation;
    loading = true; error = '';
    try {
      const response = await api.conversations.list(append ? cursor : null, {
        agentId, contextType: 'web', status: 'active', includeAgentDirect: false,
        query: query.trim() || null, limit: 30,
      }, { signal: controller.signal });
      if (request !== generation) return;
      const items = response.items.filter((item) => item.agent_id === agentId
        && item.context.type === 'web' && !isTaskControlConversationSummary(item)
        && !['task', 'task_step', 'external_channel'].includes(item.conversation_state?.conversation_kind ?? ''));
      rows = [...new Map([...(append ? rows : []), ...items].map((item) => [item.conversation_id, item])).values()];
      cursor = response.has_more ? response.cursor : null;
    } catch (cause) {
      if (request === generation && !controller?.signal.aborted) error = asApiError(cause).message || 'Could not load conversations.';
    } finally { if (request === generation) loading = false; }
  }
  $effect(() => {
    void agentId; void query; void owner;
    rows = []; cursor = null; loading = true; error = '';
    const timer = setTimeout(() => void load(), query ? 200 : 0);
    return () => { clearTimeout(timer); generation++; controller?.abort(); };
  });
  $effect(() => { if (input) void tick().then(() => input?.focus()); });
</script>

<div class="flex min-h-0 flex-1 flex-col" data-testid="pinned-conversation-picker">
  <label class="m-3 flex shrink-0 items-center gap-2 rounded-xl border border-control-border bg-surface px-3 py-2 focus-within:border-accent">
    <Search class="h-4 w-4 text-quiet" />
    <input use:findTarget bind:this={input} bind:value={query} aria-label="Filter recent conversations" placeholder="Search conversations…"
      class="min-w-0 flex-1 bg-transparent text-sm text-foreground placeholder:text-muted outline-none" />
  </label>
  <p class="px-4 pb-2 text-[10px] font-semibold uppercase tracking-wider text-quiet">Recent web conversations</p>
  <div class="min-h-0 flex-1 overflow-y-auto px-2 pb-3" aria-busy={loading}>
    {#each rows as row (row.conversation_id)}
      {@const conversation = $pinnedConversations[row.conversation_id] ?? row}
      {@const todos = conversation.conversation_state?.active_session.todos ?? []}
      <div class="flex items-center gap-2 rounded-xl pr-2 hover:bg-surface-hover">
        <button type="button" class="flex min-w-0 flex-1 items-center gap-3 p-3 text-left"
          onclick={() => void onOpen(conversation)} title={conversation.title ?? 'Untitled conversation'}>
          <ActivityAvatar name={agent?.display_name ?? agent?.name ?? 'Agent'} avatarUrl={agent?.avatar_url}
            draggable={false} state={conversationActivityState(conversation, { backgroundWork: $pinnedBackgroundWork })} class="h-8 w-8" />
          <span class="min-w-0 flex-1 truncate text-sm text-foreground">{conversation.title ?? 'Untitled conversation'}</span>
          {#if conversation.starred_at}<Star class="h-3.5 w-3.5 shrink-0 fill-orange-tone text-orange-tone" aria-label="Bookmarked" />{/if}
        </button>
        {#if todos.length}
          <TodoProgressPopover todos={todos.map((item) => ({ ...item, priority: item.priority ?? 'medium' }))}
            size="sm" placement="bottom-right" label="Conversation todo progress" />
        {/if}
      </div>
    {/each}
    {#if error && !net.hideErrors}<p class="p-3 text-sm text-danger" role="alert">{error} <button class="text-accent hover:text-accent-hover" onclick={() => void load()}>Retry</button></p>
    {:else if (loading || error) && !rows.length}<p class="p-4 text-center text-sm text-quiet">Loading…</p>
    {:else if !rows.length}<p class="p-4 text-center text-sm text-quiet">No matching conversations.</p>{/if}
    {#if cursor && !loading}<button class="w-full rounded-lg p-2 text-sm text-accent hover:text-accent-hover hover:bg-surface-hover" onclick={() => void load(true)}>Load more</button>{/if}
  </div>
</div>
