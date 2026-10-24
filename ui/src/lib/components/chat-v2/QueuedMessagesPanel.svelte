<script lang="ts">
  import Button from '$lib/components/ui/Button.svelte';
  import { chatV2Api } from '$lib/chat-v2/api';
  import {
    isAutomaticContinuation,
    queuedMessageAccessibleLabel,
    queuedMessageLabel,
    visibleQueuedMessages,
  } from '$lib/chat-v2/queue-presentation';
  import type { QueueMessage, QueueMutationResponse } from '$lib/chat-v2/types';
  import { confirmAction } from '$lib/stores/confirm';

  let {
    conversationId,
    messages,
    compact = false,
    onMutation
  } = $props<{
    conversationId: string;
    messages: QueueMessage[];
    compact?: boolean;
    onMutation: (
      response: QueueMutationResponse,
      mutation: { kind: 'update'; message: QueueMessage; content: string } | { kind: 'delete'; message: QueueMessage }
    ) => void | Promise<void>;
  }>();

  let busyId = $state<string | null>(null);
  let editingId = $state<string | null>(null);
  let editContent = $state('');
  let error = $state('');
  let expandedIds = $state<Set<string>>(new Set());
  let conversationGeneration = 0;
  let generationConversationId = '';
  const visibleMessages = $derived(visibleQueuedMessages(messages));

  $effect(() => {
    if (conversationId === generationConversationId) return;
    generationConversationId = conversationId;
    conversationGeneration += 1;
    busyId = null;
    expandedIds = new Set();
    cancelEdit();
  });

  function toggleExpanded(queueId: string): void {
    const next = new Set(expandedIds);
    if (next.has(queueId)) {
      next.delete(queueId);
    } else {
      next.add(queueId);
    }
    expandedIds = next;
  }

  function startEdit(message: QueueMessage): void {
    if (message.status === 'committing' || !message.can_edit) return;
    editingId = message.queue_id;
    editContent = message.content;
    error = '';
  }

  function cancelEdit(): void {
    editingId = null;
    editContent = '';
    error = '';
  }

  async function save(queueId: string): Promise<void> {
    const current = visibleMessages.find((message) => message.queue_id === queueId);
    if (!current?.can_edit || current.status === 'committing') {
      cancelEdit();
      return;
    }
    const content = editContent.trim();
    if (!content) {
      error = 'Queued message cannot be empty.';
      return;
    }
    const message = messages.find((item: QueueMessage) => item.queue_id === queueId);
    if (!message) {
      error = 'Queued message not found.';
      return;
    }
    const targetConversationId = conversationId;
    const targetGeneration = conversationGeneration;
    busyId = queueId;
    error = '';
    try {
      const response = await chatV2Api.updateQueuedMessage(targetConversationId, queueId, {
        client_txn_id: crypto.randomUUID(),
        content
      });
      if (conversationId !== targetConversationId || conversationGeneration !== targetGeneration) return;
      await onMutation(response, { kind: 'update', message, content });
      cancelEdit();
    } catch (caught) {
      if (conversationId !== targetConversationId || conversationGeneration !== targetGeneration) return;
      error = caught instanceof Error ? caught.message : 'Could not update the queued message.';
    } finally {
      if (conversationGeneration === targetGeneration) busyId = null;
    }
  }

  async function remove(message: QueueMessage): Promise<void> {
    if (message.status === 'committing') return;
    const targetConversationId = conversationId;
    const targetGeneration = conversationGeneration;
    const confirmed = await confirmAction({
      title: 'Delete queued message?',
      message: 'This message will not be sent. Other queued messages will keep their current order.',
      confirmLabel: 'Delete',
      variant: 'danger'
    });
    if (
      !confirmed
      || conversationId !== targetConversationId
      || conversationGeneration !== targetGeneration
    ) return;
    busyId = message.queue_id;
    error = '';
    try {
      const response = await chatV2Api.deleteQueuedMessage(targetConversationId, message.queue_id, {
        client_txn_id: crypto.randomUUID()
      });
      if (conversationId !== targetConversationId || conversationGeneration !== targetGeneration) return;
      await onMutation(response, { kind: 'delete', message });
      if (editingId === message.queue_id) cancelEdit();
    } catch (caught) {
      if (conversationId !== targetConversationId || conversationGeneration !== targetGeneration) return;
      error = caught instanceof Error ? caught.message : 'Could not delete the queued message.';
    } finally {
      if (conversationGeneration === targetGeneration) busyId = null;
    }
  }
</script>

{#if visibleMessages.length > 0}
  <section class={`shrink-0 border-t border-separator bg-inset ${compact ? 'px-3 py-2' : 'px-3 py-2.5'}`} aria-label="Queued messages">
    {#if error}<p class="mt-1 text-xs text-danger" role="alert">{error}</p>{/if}
    <div class="max-h-48 space-y-1.5 overflow-auto">
      {#each visibleMessages as message (message.queue_id)}
        {@const automatic = isAutomaticContinuation(message)}
        {@const committing = message.status === 'committing'}
        {@const expanded = expandedIds.has(message.queue_id)}
        {@const accessibleLabel = queuedMessageAccessibleLabel(message)}
        <div class="rounded-lg bg-surface p-2">
          <div class="flex min-w-0 flex-wrap items-center gap-2">
            <p class="queue-message-text min-w-0 flex-1 truncate text-foreground">{queuedMessageLabel(message)}</p>
            <Button
              size="sm"
              variant="ghost"
              aria-expanded={expanded}
              aria-label={`${expanded ? 'Collapse' : 'Expand'} queued message: ${accessibleLabel}`}
              onclick={() => toggleExpanded(message.queue_id)}
            >
              {expanded ? 'Collapse' : 'Details'}
            </Button>
            {#if committing}
              <span class="shrink-0 text-[11px] font-medium text-info">Committing…</span>
            {:else if !automatic}
              {#if message.can_edit}
              <Button size="sm" variant="secondary" disabled={busyId !== null} aria-label={`Edit queued message: ${accessibleLabel}`} onclick={() => startEdit(message)}>Edit</Button>
              {/if}
              <Button size="sm" variant="danger" disabled={busyId !== null} aria-label={`${busyId === message.queue_id ? 'Deleting' : 'Delete'} queued message: ${accessibleLabel}`} onclick={() => void remove(message)}>
                {busyId === message.queue_id ? 'Deleting…' : 'Delete'}
              </Button>
            {/if}
          </div>
          {#if expanded}
            <div class="mt-2 rounded-lg bg-inset p-2.5">
              <p class="queue-message-text max-h-48 overflow-auto whitespace-pre-wrap break-words text-foreground">{message.content || queuedMessageLabel(message)}</p>
              {#if message.attachments?.length}
                <p class="mt-1 text-[11px] text-secondary">{message.attachments.length} attachment{message.attachments.length === 1 ? '' : 's'}</p>
              {/if}
            </div>
          {/if}
            {#if editingId === message.queue_id && !committing && message.can_edit}
            <div class="mt-2">
              <textarea
                class="queue-message-text min-h-20 w-full resize-y rounded-lg border border-control-border bg-surface px-2.5 py-2 text-foreground outline-none focus:border-accent"
                bind:value={editContent}
                disabled={busyId === message.queue_id}
                aria-label={`Edit queued message: ${accessibleLabel}`}
              ></textarea>
              {#if message.attachments?.length}
                <p class="mt-1 text-[11px] text-secondary">{message.attachments.length} attachment{message.attachments.length === 1 ? '' : 's'} will be preserved.</p>
              {/if}
              <div class="mt-2 flex justify-end gap-2">
                <Button size="sm" variant="ghost" disabled={busyId !== null} onclick={cancelEdit}>Cancel</Button>
                <Button size="sm" variant="primary" disabled={busyId === message.queue_id || !editContent.trim()} onclick={() => void save(message.queue_id)}>
                  {busyId === message.queue_id ? 'Saving…' : 'Save'}
                </Button>
              </div>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  </section>
{/if}

<style>
  .queue-message-text { font-size: var(--chat-message-font-size); }
</style>
