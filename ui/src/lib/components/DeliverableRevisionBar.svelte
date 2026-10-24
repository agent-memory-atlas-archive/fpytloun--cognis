<script lang="ts">
  import { api } from '$lib/api/client';
  import { hasRevisionHistory, isSupersededRevision, revisionLabel } from '$lib/deliverable-revisions';
  import type { Deliverable, DeliverableRevisionSummary } from '$lib/types/api';

  // `current` is the revision on screen; `anchor` is the revision this surface
  // was opened for. History is loaded lazily, only when the user opens it.
  let {
    current,
    anchorId = current.deliverable_id,
    onSelect,
  }: {
    current: Deliverable;
    anchorId?: string;
    onSelect: (revision: DeliverableRevisionSummary) => void;
  } = $props();

  let open = $state(false);
  let loading = $state(false);
  let error = $state('');
  let revisions = $state<DeliverableRevisionSummary[] | null>(null);
  let loadedFor = '';

  const visible = $derived(hasRevisionHistory(current));
  const superseded = $derived(isSupersededRevision(current));
  const latestId = $derived(current.latest_deliverable_id ?? null);

  async function loadRevisions(): Promise<void> {
    const lineageKey = current.lineage_id ?? current.deliverable_id;
    if (revisions && loadedFor === lineageKey) return;
    loading = true;
    error = '';
    try {
      const result = await api.deliverables.revisions(anchorId);
      revisions = result.revisions;
      loadedFor = lineageKey;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Could not load revisions';
    } finally {
      loading = false;
    }
  }

  function toggle(): void {
    open = !open;
    if (open) void loadRevisions();
  }

  function select(revision: DeliverableRevisionSummary): void {
    open = false;
    if (revision.deliverable_id !== current.deliverable_id) onSelect(revision);
  }

  // The summary carries the owning step run, which selects the detail endpoint.
  async function showLatest(): Promise<void> {
    await loadRevisions();
    const latest = revisions?.find((item) => item.deliverable_id === latestId)
      ?? revisions?.find((item) => item.is_latest);
    if (latest) select(latest);
  }

  function formatDate(value: string | null): string {
    if (!value) return '';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
  }
</script>

{#if visible}
  <div class="revision-bar" data-testid="deliverable-revision-bar" data-superseded={superseded ? 'true' : undefined}>
    <div class="flex flex-wrap items-center gap-2 text-xs">
      <button
        type="button"
        class="inline-flex items-center gap-1 rounded-full border border-control-border bg-surface/80 px-2.5 py-1 font-medium text-foreground hover:border-accent"
        aria-expanded={open}
        aria-haspopup="listbox"
        data-testid="deliverable-revision-toggle"
        onclick={toggle}
      >
        {revisionLabel(current.revision, current.latest_revision)}
        <span aria-hidden="true" class="text-quiet">▾</span>
      </button>
      {#if superseded}
        <span class="rounded-full border border-warning-border bg-warning-subtle px-2.5 py-1 text-warning" data-testid="deliverable-superseded-notice">
          Superseded by revision {current.latest_revision}
        </span>
        {#if latestId}
          <button type="button" class="text-accent hover:text-accent-hover" data-testid="deliverable-view-latest" onclick={() => void showLatest()}>View latest</button>
        {/if}
      {:else if current.deliverable_id !== anchorId}
        <span class="rounded-full border border-info-border bg-info-subtle px-2.5 py-1 text-info">Latest</span>
      {/if}
    </div>
    {#if open}
      <div class="mt-2 rounded-xl border border-control-border bg-elevated/95 p-1 shadow-lg" role="listbox" aria-label="Deliverable revisions" data-testid="deliverable-revision-list">
        {#if loading}
          <p class="px-3 py-2 text-xs text-muted">Loading revisions…</p>
        {:else if error}
          <p class="px-3 py-2 text-xs text-danger">{error}</p>
        {:else if revisions}
          {#each revisions as revision (revision.deliverable_id)}
            <button
              type="button"
              role="option"
              aria-selected={revision.deliverable_id === current.deliverable_id}
              class={`flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-xs ${revision.deliverable_id === current.deliverable_id ? 'bg-accent-subtle text-strong' : 'text-secondary hover:bg-surface-hover'}`}
              data-testid="deliverable-revision-option"
              data-deliverable-id={revision.deliverable_id}
              onclick={() => select(revision)}
            >
              <span class="min-w-0">
                <span class="font-medium">Revision {revision.revision}</span>
                {#if revision.title}<span class="ml-1 truncate text-muted">· {revision.title}</span>{/if}
                {#if revision.task_id}<span class="ml-1 text-quiet">· task output</span>{/if}
              </span>
              <span class="flex shrink-0 items-center gap-2 text-quiet">
                {formatDate(revision.created_at)}
                {#if revision.is_latest}<span class="rounded-full bg-info-subtle px-1.5 py-0.5 text-info">Latest</span>{/if}
              </span>
            </button>
          {/each}
        {/if}
      </div>
    {/if}
  </div>
{/if}

<style>
  .revision-bar {
    margin-bottom: 0.5rem;
  }
</style>
