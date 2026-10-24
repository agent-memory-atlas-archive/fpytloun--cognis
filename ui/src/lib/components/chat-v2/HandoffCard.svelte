<script lang="ts">
  import Copy from 'lucide-svelte/icons/copy';
  import MessageSquarePlus from 'lucide-svelte/icons/message-square-plus';
  import ChevronRight from 'lucide-svelte/icons/chevron-right';
  import LoaderCircle from 'lucide-svelte/icons/loader-circle';
  import ArrowUpRight from 'lucide-svelte/icons/arrow-up-right';
  import { renderMarkdown } from '$lib/markdown';
  import type { HandoffTimelineItem } from '$lib/chat-v2/types';

  let { item, onNewConversation } = $props<{
    item: HandoffTimelineItem;
    onNewConversation?: (item: HandoffTimelineItem) => void;
  }>();
  let expanded = $state(false);
  let copyStatus = $state('');
  const completed = $derived((item.status ?? 'complete') === 'complete');

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(item.text);
      copyStatus = 'Copied';
    } catch {
      copyStatus = 'Copy failed. Expand and select the text to copy it.';
    }
  }
</script>

<section class="w-full rounded-2xl border border-blue-border bg-surface/90 px-5 py-4 shadow-sm" aria-label="Conversation handoff">
  <div class="flex items-center justify-between gap-3">
    <button type="button" class="flex min-w-0 items-center gap-2 text-left text-blue-tone"
      disabled={!completed}
      aria-expanded={expanded} onclick={() => expanded = !expanded}>
      {#if item.status === 'running'}
        <LoaderCircle class="h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none" />
      {:else}
        <ChevronRight class={`h-4 w-4 shrink-0 transition-transform ${expanded ? 'rotate-90' : ''}`} />
      {/if}
      <span class="text-xs font-semibold uppercase tracking-[0.18em]">Handoff</span>
      {#if item.focus}<span class="truncate text-xs font-normal normal-case tracking-normal text-muted">{item.focus}</span>{/if}
    </button>
    {#if completed}
    <div class="flex shrink-0 items-center gap-1">
      <button type="button" class="rounded-lg p-2 text-secondary hover:bg-surface-hover hover:text-accent"
        aria-label="Copy handoff" title="Copy handoff" onclick={() => void copy()}><Copy class="h-4 w-4" /></button>
      {#if item.recipient_conversation_id}
        <a class="flex items-center gap-1 rounded-lg p-2 text-sm text-blue-tone hover:bg-surface-hover"
          href={`/chat/${encodeURIComponent(item.recipient_conversation_id)}`} aria-label="Open handoff conversation">
          Open conversation <ArrowUpRight class="h-4 w-4" />
        </a>
      {:else if onNewConversation}
        <button type="button" class="rounded-lg p-2 text-secondary hover:bg-surface-hover hover:text-accent"
          aria-label="New conversation from handoff" title="New conversation from handoff"
          onclick={() => onNewConversation?.(item)}><MessageSquarePlus class="h-4 w-4" /></button>
      {/if}
    </div>
    {/if}
  </div>
  {#if item.status === 'running'}
    <p role="status" class="mt-2 text-sm text-muted">Preparing handoff…</p>
  {:else if item.status === 'failed'}
    <p role="alert" class="mt-2 text-sm text-danger">{item.error || 'Handoff generation failed. Please try again.'}</p>
  {/if}
  {#if copyStatus}<p role="status" class="mt-2 text-xs text-muted">{copyStatus}</p>{/if}
  {#if expanded && completed}
    <div class="chat-markdown prose prose-sm mt-3 max-h-[60vh] max-w-none overflow-y-auto break-words text-foreground">
      {@html renderMarkdown(item.text)}
    </div>
  {/if}
</section>
