<script lang="ts">
  import AssistantDeliverableBlock from '$lib/components/AssistantDeliverableBlock.svelte';
  import MessageAttachments from '$lib/components/MessageAttachments.svelte';
  import { renderMarkdown } from '$lib/markdown';
  import type { RecapTimelineItem, WorkCategory } from '$lib/chat-v2/types';

  let {
    item,
    onOpenWork
  } = $props<{
    item: RecapTimelineItem;
    onOpenWork?: (category: WorkCategory, sessionId: string, path?: string, sourceItemId?: string) => void;
  }>();
  let selectedDeliverable = $state<{ id: string; title: string } | null>(null);
  let showArtifacts = $state(false);
  const totalAdditions = $derived(item.files.reduce((sum: number, file: RecapTimelineItem['files'][number]) => sum + (file.additions ?? 0), 0));
  const totalDeletions = $derived(item.files.reduce((sum: number, file: RecapTimelineItem['files'][number]) => sum + (file.deletions ?? 0), 0));
  const hasCompleteFileStats = $derived(
    item.stats_version >= 2 && !item.file_diffs_omitted &&
    item.files.every((file: RecapTimelineItem['files'][number]) =>
      typeof file.additions === 'number' && typeof file.deletions === 'number'
    )
  );
</script>

<section class="w-full max-h-[300px] overflow-y-auto rounded-2xl border border-sky-500/25 bg-slate-900/90 px-5 py-4 shadow-sm" aria-label="Conversation recap">
  <div class="mb-2 flex items-center justify-between gap-3">
    <h3 class="text-xs font-semibold uppercase tracking-[0.18em] text-sky-300">Recap</h3>
    <span class="text-xs text-slate-500">{item.scope === 'recent_window' ? 'Recent work' : 'Earlier recap'} · {item.auto ? 'Automatic' : 'On request'}</span>
  </div>
  <div class="chat-markdown prose prose-invert prose-sm max-w-none break-words text-slate-100 prose-p:my-1 prose-a:text-sky-300 prose-a:underline prose-a:underline-offset-2">
    {@html renderMarkdown(item.text)}
  </div>
  {#if item.deliverables.length || item.artifacts.length || item.files.length}
    <div class="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-700/70 pt-3 text-xs">
      {#each item.deliverables as deliverable (deliverable.id)}
        <button type="button" class="max-w-[220px] truncate rounded-lg border border-slate-600 px-2.5 py-1.5 text-slate-200 hover:border-sky-400" title={deliverable.title} onclick={() => selectedDeliverable = deliverable}>
          {deliverable.title}
        </button>
      {/each}
      {#if item.artifacts.length}
        <button type="button" class="rounded-lg border border-slate-600 px-2.5 py-1.5 text-slate-200 hover:border-sky-400" onclick={() => showArtifacts = true}>
          {item.artifacts.length} artifact{item.artifacts.length === 1 ? '' : 's'} ↗
        </button>
      {/if}
      {#if item.files.length}
        <button type="button" class="rounded-lg border border-slate-600 px-2.5 py-1.5 text-slate-200 hover:border-sky-400" onclick={() => onOpenWork?.('files', item.source_session_id, item.files[0].path, item.id)}>
          {item.files.length}{item.file_diffs_omitted ? '+' : ''} file{item.files.length === 1 && !item.file_diffs_omitted ? '' : 's'}
          {#if hasCompleteFileStats}
            <span class="text-emerald-300">+{totalAdditions}</span> <span class="text-rose-300">−{totalDeletions}</span>
          {:else}
            <span class="text-slate-400">diff stats unavailable</span>
          {/if}
          ↗
        </button>
      {/if}
    </div>
  {/if}
</section>

{#if selectedDeliverable}
  <div class="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 p-4" role="presentation" onclick={() => selectedDeliverable = null}>
    <div role="dialog" tabindex="-1" aria-modal="true" aria-label={selectedDeliverable.title} class="max-h-[90vh] w-full max-w-5xl overflow-auto rounded-2xl bg-slate-900 p-5 shadow-2xl" onclick={(event) => event.stopPropagation()} onkeydown={(event) => { if (event.key === 'Escape') selectedDeliverable = null; }}>
      <div class="mb-3 flex items-center justify-between gap-3">
        <h3 class="text-lg font-semibold">{selectedDeliverable.title}</h3>
        <button type="button" class="text-sm text-sky-300" onclick={() => selectedDeliverable = null}>Close</button>
      </div>
      <AssistantDeliverableBlock item={{ ...item, kind: 'assistant_deliverable', deliverable_id: selectedDeliverable.id, format: 'markdown', title: selectedDeliverable.title }} />
    </div>
  </div>
{/if}

{#if showArtifacts}
  <div class="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 p-4" role="presentation" onclick={() => showArtifacts = false}>
    <div role="dialog" tabindex="-1" aria-modal="true" aria-label="Recap artifacts" class="max-h-[90vh] w-full max-w-3xl overflow-auto rounded-2xl bg-slate-900 p-5 shadow-2xl" onclick={(event) => event.stopPropagation()} onkeydown={(event) => { if (event.key === 'Escape') showArtifacts = false; }}>
      <div class="mb-4 flex items-center justify-between">
        <h3 class="text-lg font-semibold">Artifacts</h3>
        <button type="button" class="text-sm text-sky-300" onclick={() => showArtifacts = false}>Close</button>
      </div>
      <MessageAttachments attachments={item.artifacts.map((artifact: RecapTimelineItem['artifacts'][number]) => ({ artifact_id: artifact.id, filename: artifact.title, kind: 'file', mime_type: artifact.mime_type, size_bytes: artifact.size_bytes }))} />
      <button type="button" class="mt-4 text-sm text-sky-300 hover:underline" onclick={() => { showArtifacts = false; onOpenWork?.('artifacts', item.source_session_id); }}>Open in Work sidebar →</button>
    </div>
  </div>
{/if}
