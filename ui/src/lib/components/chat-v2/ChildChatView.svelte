<script lang="ts">
  import ParentChatLink from './ParentChatLink.svelte';
  import Check from 'lucide-svelte/icons/check';
  import Copy from 'lucide-svelte/icons/copy';
  import X from 'lucide-svelte/icons/x';
  import ExternalLink from 'lucide-svelte/icons/external-link';
  import AgentAvatar from '$lib/components/AgentAvatar.svelte';
  import SessionLogHeader from './SessionLogHeader.svelte';
  import SessionDetailsButton from '$lib/components/session/SessionDetailsButton.svelte';
  import ScopedChatV2Timeline, { type ScopedChatV2Realtime } from './ScopedChatV2Timeline.svelte';
  import type { ChatV2ApiClient } from '$lib/chat-v2/api';
  import TimelineOngoingWorkDrawer from '$lib/components/timeline/TimelineOngoingWorkDrawer.svelte';
  import ManagedConversationControls from '$lib/components/ManagedConversationControls.svelte';
  import { childViewScope, type ChildView } from '$lib/childView';
  import type { WorkstreamRef } from '$lib/chat-v2/types';
  import type { Agent, BackgroundWorkItem, Conversation, UserPreferences } from '$lib/types/api';
  import type { TodoSnapshotItem } from '$lib/todos';
  import { onDestroy } from 'svelte';
  import {
    displaySessionStatus,
    isTerminalSessionStatus,
  } from '$lib/session-status';

  let { view, node, agent = null, preferences, work = [], workTruncated = false, managedConversation = null, managedBusy = null, managedError = '', inspectorOpen, userScrolledUp = $bindable(false), todos = $bindable([]), timelineApi, timelineRealtime, onBack, onClose, onToggleInspector, onViewSession, onRuntimeActiveChange, onManagedStop, onManagedSend, onManagedTakeControl } = $props<{
    view: ChildView; node: WorkstreamRef; agent?: Agent | null; preferences: UserPreferences;
    work?: BackgroundWorkItem[]; workTruncated?: boolean;
    managedConversation?: Conversation | null; managedBusy?: string | null; managedError?: string;
    timelineApi?: Pick<ChatV2ApiClient, 'snapshot' | 'sync' | 'timeline'>;
    timelineRealtime?: ScopedChatV2Realtime;
    inspectorOpen: boolean; userScrolledUp?: boolean; todos?: TodoSnapshotItem[]; onBack: () => void; onClose: () => void;
    onToggleInspector: (trigger: HTMLElement) => void;
    onViewSession: (sessionId: string, node?: WorkstreamRef) => void;
    onRuntimeActiveChange?: (active: boolean) => void;
    onManagedStop?: () => void; onManagedSend?: (message: string) => void; onManagedTakeControl?: () => void;
  }>();
  let copied = $state(false);
  let ongoingWorkOpen = $state(false);
  const scope = $derived(childViewScope(view));
  const displayName = $derived(node.agent_display_name ?? agent?.display_name ?? agent?.name ?? node.agent_id);
  const avatarUrl = $derived(node.agent_avatar_url ?? agent?.avatar_url ?? null);
  const normalizedStatus = $derived(displaySessionStatus(node.status, node.activity_state, false, node.execution_state));
  async function copySessionId(): Promise<void> {
    await navigator.clipboard?.writeText(view.sessionId);
    copied = true;
    window.setTimeout(() => { copied = false; }, 1200);
  }
  function handleTodosChange(next: TodoSnapshotItem[]): void {
    todos = next;
  }
  onDestroy(() => onRuntimeActiveChange?.(false));
</script>

<section
  class="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-transparent"
  style="padding-bottom: var(--app-bottom-control-inset);"
  data-testid="child-chat-view"
>
  <SessionLogHeader title={node.title} testId="child-header">
    {#snippet leading()}
      <ParentChatLink conversationId={view.controllerRootConversationId} {onBack} />
      <AgentAvatar name={displayName} {avatarUrl} class="h-8 w-8 shrink-0" />
    {/snippet}
    {#snippet metadata()}
      <div class="flex min-w-0 gap-1 text-xs text-muted">
        <span class="truncate text-foreground">{displayName}</span>
        <span aria-hidden="true">·</span><span class="shrink-0">{normalizedStatus}</span>
      </div>
    {/snippet}
    {#snippet actions()}
      <button class="touch-target-compact inline-flex shrink-0 items-center justify-center rounded-lg border border-control-border text-muted hover:bg-surface-hover hover:text-foreground" type="button" aria-label="Copy canonical session ID" title="Copy canonical session ID" onclick={() => void copySessionId()}>
        {#if copied}<Check class="h-4 w-4 text-success" />{:else}<Copy class="h-4 w-4" />{/if}
      </button>
      {#if view.kind === 'managed'}
        <a
          class="touch-target-compact inline-flex shrink-0 items-center justify-center rounded-lg border border-control-border text-muted transition hover:bg-surface-hover hover:text-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
          href={`/chat/${encodeURIComponent(view.conversationId)}`}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Open ${node.title} in new window`}
        ><ExternalLink class="h-4 w-4" /></a>
      {/if}
      <SessionDetailsButton open={inspectorOpen} ariaControls="conversation-info-drawer" testId="child-header-inspector" onclick={(event) => onToggleInspector(event.currentTarget as HTMLElement)} />
      <button class="touch-target-compact inline-flex shrink-0 items-center justify-center rounded-lg border border-control-border text-muted hover:bg-surface-hover hover:text-strong" type="button" aria-label="Close child conversation" onclick={onClose}><X class="h-4 w-4" /></button>
    {/snippet}
  </SessionLogHeader>
  {#if work.length || todos.length}
    <div class="shrink-0 px-4 pt-3">
      <TimelineOngoingWorkDrawer {todos} {work} truncated={workTruncated} bind:open={ongoingWorkOpen} {onViewSession} />
    </div>
  {/if}
  <ScopedChatV2Timeline {scope} {agent} {preferences} bind:userScrolledUp {onViewSession} {onRuntimeActiveChange} onTodosChange={handleTodosChange} api={timelineApi} realtime={timelineRealtime} activityStatus={node.execution_state ?? (isTerminalSessionStatus(node.status) ? node.status : node.activity_state === 'ongoing' ? 'running' : node.status)} emptyLabel="No events recorded yet." />
  {#if view.kind === 'managed' && managedConversation && onManagedStop && onManagedSend && onManagedTakeControl}
    <div class="shrink-0 p-3">
      <ManagedConversationControls conversation={managedConversation} busy={managedBusy} error={managedError} onStop={onManagedStop} onSend={onManagedSend} onTakeControl={onManagedTakeControl} />
    </div>
  {/if}
</section>
