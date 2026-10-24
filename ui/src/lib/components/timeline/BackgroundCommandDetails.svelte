<script lang="ts">
  import { api } from '$lib/api/client';
  import type { BackgroundCommandDetail, BackgroundWorkItem } from '$lib/types/api';

  let { item, onViewSession } = $props<{
    item: BackgroundWorkItem;
    onViewSession?: (sessionId: string) => void;
  }>();
  let detail = $state<BackgroundCommandDetail | null>(null);
  let loading = $state(false);
  let error = $state('');
  let generation = 0;

  function openSource(): void {
    if (item.session_id) onViewSession?.(item.session_id);
  }

  $effect(() => {
    const conversationId = item.controller_conversation_id;
    const shellId = item.work_id;
    detail = null;
    void load(conversationId, shellId);
    return () => { generation += 1; };
  });

  async function load(conversationId: string, shellId: string): Promise<void> {
    const requestGeneration = ++generation;
    loading = true;
    error = '';
    try {
      const result = await api.conversations.backgroundCommand(conversationId, shellId);
      if (requestGeneration === generation) detail = result;
    } catch (caught) {
      if (requestGeneration === generation) {
        error = caught instanceof Error ? caught.message : 'Could not load command details.';
      }
    } finally {
      if (requestGeneration === generation) loading = false;
    }
  }
</script>

<div class="mt-2 min-w-0 space-y-2 border-t border-separator pt-2 text-xs">
  <div class="flex flex-wrap items-center gap-2">
    <button type="button" class="min-h-10 rounded px-2 text-accent hover:text-accent-hover hover:bg-surface-hover disabled:opacity-50" disabled={loading} onclick={() => void load(item.controller_conversation_id, item.work_id)}>
      {loading ? 'Loading…' : 'Refresh details'}
    </button>
    {#if item.session_id && onViewSession}
      <button type="button" class="min-h-10 rounded px-2 text-accent hover:text-accent-hover hover:bg-surface-hover" onclick={openSource}>Open source session</button>
    {/if}
  </div>
  {#if error}<p role="alert" class="break-words text-danger">{error}</p>{/if}
  {#if detail}
    <pre class="max-w-full overflow-auto whitespace-pre-wrap break-words rounded bg-inset p-2 text-foreground" aria-label="Command">{detail.command}</pre>
    <dl class="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-muted">
      <dt>Shell</dt><dd class="break-all">{detail.shell_id}</dd>
      <dt>Executor</dt><dd class="break-all">{detail.executor_id}</dd>
      <dt>Directory</dt><dd class="break-all">{detail.cwd ?? 'Not available'}</dd>
      <dt>Process</dt><dd>{detail.pid ?? 'Not available'}</dd>
      <dt>Status</dt><dd>{detail.status}{#if detail.exit_code !== null} · exit {detail.exit_code}{/if}</dd>
      <dt>Runtime</dt><dd>{Math.floor(detail.runtime_seconds)}s · idle {Math.floor(detail.idle_seconds)}s</dd>
    </dl>
    <p class="text-quiet">Latest output tail · {detail.output_chars.toLocaleString()} buffered characters{#if detail.trimmed_chars > 0} · earlier output trimmed{/if}</p>
    <pre class="max-h-48 max-w-full overflow-auto whitespace-pre-wrap break-words rounded bg-inset p-2 font-mono text-foreground" aria-label="Latest command output">{detail.output_tail || 'No output yet.'}</pre>
  {/if}
</div>
