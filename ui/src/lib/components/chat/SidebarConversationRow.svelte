<script lang="ts">
  import Star from 'lucide-svelte/icons/star';

  import ActivityAvatar from '$lib/components/ActivityAvatar.svelte';
  import TodoProgressPopover from '$lib/components/TodoProgressPopover.svelte';
  import { isAttentionActionQuickAction } from '$lib/attention/actions';
  import type { ActivityAvatarState } from '$lib/conversation-activity';
  import type {
    AttentionActionSummary,
    Conversation,
    ConversationTodoItem,
  } from '$lib/types/api';

  interface Props {
    conversation: Conversation;
    href: string;
    agentName: string;
    agentAvatarUrl?: string | null;
    avatarState: ActivityAvatarState;
    active: boolean;
    unread: boolean;
    dense: boolean;
    waitingReason?: string | null;
    canStar: boolean;
    starBusy: boolean;
    todoProgress?: Array<ConversationTodoItem & { priority: string }>;
    showTodoProgress?: boolean;
    contextBadge?: string | null;
    onNavigate: () => void;
    onToggleStar: (event: MouseEvent) => void;
    onOpenAttention: (action: AttentionActionSummary, origin: HTMLElement) => void;
  }

  let {
    conversation,
    href,
    agentName,
    agentAvatarUrl = null,
    avatarState,
    active,
    unread,
    dense,
    waitingReason = null,
    canStar,
    starBusy,
    todoProgress = [],
    showTodoProgress = false,
    contextBadge = null,
    onNavigate,
    onToggleStar,
    onOpenAttention,
  }: Props = $props();

  function openAttention(event: MouseEvent, action: AttentionActionSummary): void {
    event.preventDefault();
    event.stopPropagation();
    onOpenAttention(action, event.currentTarget as HTMLElement);
  }
</script>

{#snippet attentionActions(denseMode: boolean)}
  {#each conversation.attention_actions ?? [] as action (action.action_id)}
    {#if isAttentionActionQuickAction(action)}
      <button
        type="button"
        aria-label={`${action.title} for ${conversation.title ?? 'conversation'}`}
        class={`shrink-0 rounded-lg border border-amber-400/40 bg-amber-400/10 font-medium text-amber-100 hover:bg-amber-400/20 ${denseMode ? 'px-1.5 py-1 text-[10px]' : 'px-2 py-1.5 text-xs'}`}
        data-testid={`sidebar-attention-${action.action_id}`}
        onclick={(event) => openAttention(event, action)}
      >{action.title}</button>
    {/if}
  {/each}
{/snippet}

{#snippet todoIndicator()}
  {#if showTodoProgress}
    <TodoProgressPopover
      todos={todoProgress}
      size="sm"
      placement="bottom-right"
      class="text-emerald-300"
      label="Conversation todo progress"
    />
  {/if}
{/snippet}

{#snippet rowIndicators(todoFirst: boolean)}
  {#if todoFirst}
    {@render todoIndicator()}
  {/if}
  {#if canStar}
    <button
      aria-label={conversation.starred_at ? 'Unstar conversation' : 'Star conversation'}
      class={`rounded-lg p-1 transition hover:bg-slate-800 ${conversation.starred_at ? 'text-amber-300 hover:text-amber-200' : 'text-slate-600 hover:text-slate-200'}`}
      disabled={starBusy}
      onclick={onToggleStar}
      title={conversation.starred_at ? 'Unstar conversation' : 'Star conversation'}
      type="button"
    >
      <Star class={`h-4 w-4 ${conversation.starred_at ? 'fill-current' : ''}`} />
    </button>
  {/if}
  {#if !todoFirst}
    {@render todoIndicator()}
  {/if}
{/snippet}

<div
  class={`group flex min-w-0 items-center rounded-xl transition ${dense ? 'gap-2 px-2 py-1.5' : 'gap-2 px-2 py-2'} ${active ? 'bg-sky-500/15 text-white' : waitingReason ? 'border border-amber-500/20 bg-amber-500/5 text-slate-200 hover:border-amber-400/40' : 'text-slate-200 hover:bg-slate-900/60'}`}
  data-testid={`sidebar-conversation-row-${conversation.conversation_id}`}
>
  {#if dense}
    <a class="flex min-w-0 flex-1 items-center gap-2" {href} onclick={onNavigate} title={conversation.title ?? 'Untitled conversation'}>
      <ActivityAvatar
        name={agentName}
        avatarUrl={agentAvatarUrl}
        state={avatarState}
        class="h-7 w-7 shrink-0"
      />
      <p class={`min-w-0 overflow-x-auto whitespace-nowrap text-xs [scrollbar-width:none] [&::-webkit-scrollbar]:hidden ${unread ? 'font-semibold text-white' : 'font-medium text-white'}`}>
        {conversation.title ?? 'Untitled conversation'}
      </p>
    </a>
    {@render attentionActions(true)}
    <div class="relative z-10 flex shrink-0 items-center gap-0.5" data-testid="sidebar-dense-indicators">
      {@render rowIndicators(true)}
    </div>
  {:else}
    <a
      class="flex min-w-0 flex-1 items-center gap-2"
      {href}
      onclick={onNavigate}
      title={conversation.title ?? 'Untitled conversation'}
    >
    <ActivityAvatar
      name={agentName}
      avatarUrl={agentAvatarUrl}
      state={avatarState}
      class="h-8 w-8 shrink-0"
    />
    <div class="min-w-0 flex-1">
      <p
        class={`line-clamp-2 break-words text-sm leading-5 ${unread ? 'font-semibold text-white' : 'font-medium text-white'}`}
      >{conversation.title ?? 'Untitled conversation'}</p>
      {#if contextBadge || waitingReason}
      <div class="mt-0.5 flex items-center gap-2">
        {#if contextBadge}
          <span class="shrink-0 rounded-full border border-slate-700 bg-slate-800/60 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-widest text-slate-500">
            {contextBadge}
          </span>
        {/if}
        {#if waitingReason}
          <span class="truncate text-xs text-amber-200">{waitingReason}</span>
        {/if}
      </div>
      {/if}
    </div>
    </a>
    {@render attentionActions(false)}
    <div class="relative z-10 flex shrink-0 flex-col items-center justify-center gap-1">
      {@render rowIndicators(false)}
    </div>
  {/if}
</div>
