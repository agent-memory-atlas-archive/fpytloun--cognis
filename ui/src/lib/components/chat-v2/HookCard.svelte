<script lang="ts">
  import type { NoticeTimelineItem } from '$lib/chat-v2/types';
  import { renderMarkdown, stripMarkdown } from '$lib/markdown';
  import LoaderCircle from 'lucide-svelte/icons/loader-circle';
  let { item, onViewSession } = $props<{
    item: NoticeTimelineItem;
    onViewSession?: (sessionId: string) => void | Promise<void>;
  }>();
  const hook = $derived(item.hook);
  let expanded = $state(false);
  const detailsId = $props.id();
  const hookType = $derived(hook?.trigger === 'conversation_idle' ? 'Idle hook'
    : hook?.trigger === 'turn_completed' ? 'Turn-completed hook'
    : hook?.trigger ? `${hook.trigger.replaceAll('_', ' ')} hook` : 'Background hook');
  const active = $derived(['preparing', 'pending', 'dispatching', 'running', 'retrying'].includes(hook?.status ?? ''));
  // Also protect old events written before server-side marker stripping.
  const outcome = $derived((hook?.outcome ?? '')
    .replace(/<!--\s*hook-handoff:\s*(?:replace|retain)\s*-->/g, '').trim());
  const summary = $derived(stripMarkdown(outcome).replace(/\s+/g, ' ').trim()
    || (hook?.status === 'retrying' ? 'Continuing the unfinished session shortly…'
      : hook?.status === 'blocked' ? 'Execution stopped. Later eligible hooks can run normally.'
      : active ? 'Execution in progress…' : 'No final response was available.'));
</script>

{#if hook}
  <section class="hook-card recap-paint border text-foreground" aria-label="Background hook">
    <div class="heading">
      <strong title={item.title}>{item.title}</strong>
      <span class="hook-type text-muted" title={hookType}>{hookType}</span>
      <span role="status" class="inline-flex items-center gap-2">
        {#if active}<LoaderCircle class="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden="true" />{/if}
        {hook.status === 'dispatching' ? 'Starting' : hook.status.replaceAll('_', ' ')}
      </span>
    </div>
    <div class="summary-row text-muted">
      <span class="summary">{hook.outcome_partial ? 'Partial: ' : ''}{summary}</span>
      {#if hook.child_session_id && onViewSession}
        <button type="button" class="legacy-hook-link text-accent underline hover:text-accent-hover"
          onclick={() => onViewSession?.(hook.child_session_id!)}>Open session</button>
      {/if}
      <button type="button" class="legacy-hook-link text-accent hover:text-accent-hover"
        aria-expanded={expanded} aria-controls={detailsId}
        onclick={() => expanded = !expanded}>{expanded ? 'Collapse' : 'Expand'}</button>
    </div>
    {#if expanded}
    <div id={detailsId}>
    <div class="details text-muted">
      {#if hook.task_id}
        <a class="legacy-hook-link text-accent hover:text-accent-hover" href="/tasks/{encodeURIComponent(hook.task_id)}">Open task</a>
      {/if}
    </div>
    {#if hook.outcome_partial}
      <p class="mt-3 text-xs text-warning">Partial outcome — processing was not completed.</p>
    {/if}
    {#if outcome}
      {#if hook.result_truncated}
        <p class="mt-3 text-xs text-muted">
          Result shortened using the delegate result limit.
        </p>
      {/if}
      <div class="chat-markdown prose prose-sm mt-3 max-h-72 max-w-none overflow-y-auto break-words">
        {@html renderMarkdown(outcome)}
      </div>
    {:else if hook.outcome_available === false}
      <p class="mt-3 text-sm text-muted">No final response was available.</p>
    {/if}
    </div>
    {/if}
  </section>
{/if}

<style>
  .hook-card { width: 100%; max-width: 40rem; min-width: 0; box-sizing: border-box; border-radius: 0.5rem; padding: 0.5rem 0.75rem; margin-block: 0.5rem; }
  .heading { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, auto) auto; align-items: center; gap: 0.5rem; line-height: 1.25rem; font-size: 0.8rem; }
  .heading strong, .hook-type, .summary { min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .heading [role="status"] { text-transform: capitalize; white-space: nowrap; }
  .summary-row, .details { display: flex; align-items: center; gap: 0.5rem; font-size: 0.8rem; line-height: 1.25rem; }
  .summary { flex: 1; }
  .summary-row button { flex-shrink: 0; }
  .details { margin-top: 0.5rem; flex-wrap: wrap; }
  a { text-decoration: underline; }
</style>
