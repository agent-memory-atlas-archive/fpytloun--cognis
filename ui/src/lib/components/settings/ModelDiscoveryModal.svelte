<script lang="ts">
  import Button from '$lib/components/ui/Button.svelte';
  import Input from '$lib/components/ui/Input.svelte';
  import BlockingDialog from '$lib/components/ui/BlockingDialog.svelte';
  import { formatModelMetadata } from '$lib/providers';
  import type { ModelEntry } from '$lib/types/api';

  let { models, existingModelIds = [], onclose, onadd } = $props<{
    models: ModelEntry[];
    existingModelIds: string[];
    onclose: () => void;
    onadd: (selected: ModelEntry[]) => void;
  }>();

  let search = $state('');
  let selectedIds = $state<Set<string>>(new Set());

  let existingSet = $derived(new Set(existingModelIds));

  let filtered = $derived(
    search.trim()
      ? models.filter((m: ModelEntry) => m.model_id.toLowerCase().includes(search.trim().toLowerCase()))
      : models
  );

  let selectedCount = $derived(selectedIds.size);

  function isExisting(modelId: string): boolean {
    return existingSet.has(modelId);
  }

  function isSelected(modelId: string): boolean {
    return selectedIds.has(modelId);
  }

  function toggleModel(modelId: string): void {
    if (isExisting(modelId)) return;
    const next = new Set(selectedIds);
    if (next.has(modelId)) {
      next.delete(modelId);
    } else {
      next.add(modelId);
    }
    selectedIds = next;
  }

  function handleAdd(): void {
    const selected = models.filter((m: ModelEntry) => selectedIds.has(m.model_id));
    onadd(selected);
  }

  function formatMeta(model: ModelEntry): string {
    return formatModelMetadata(model);
  }
</script>

<BlockingDialog label="Add discovered models" onClose={onclose} titleId="model-discovery-title" panelClass="max-w-2xl">
  {#snippet header()}
    <div class="flex items-center justify-between gap-3">
      <h2 class="text-lg font-semibold text-strong" id="model-discovery-title">Add discovered models</h2>
      <Button aria-label="Close model discovery" size="icon" variant="secondary" onclick={onclose}>&times;</Button>
    </div>
  {/snippet}

  {#snippet children()}
    <!-- Search -->
    <div>
      <Input find bind:value={search} placeholder="Search models..." />
    </div>

    <!-- Model list -->
    <div class="mt-4 max-h-96 space-y-1 overflow-y-auto rounded-xl border border-separator bg-canvas/40 p-1">
      {#if filtered.length === 0}
        <p class="px-3 py-6 text-center text-sm text-quiet">No models match your search.</p>
      {:else}
        {#each filtered as entry}
          {@const existing = isExisting(entry.model_id)}
          {@const selected = existing || isSelected(entry.model_id)}
          <button
            type="button"
            class="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition {existing
              ? 'cursor-default opacity-50'
              : 'hover:bg-raised/60 cursor-pointer'}"
            onclick={() => toggleModel(entry.model_id)}
            disabled={existing}
          >
            <input
              type="checkbox"
              checked={selected}
              disabled={existing}
              class="shrink-0 rounded border-control-border bg-canvas text-accent focus:ring-accent"
              tabindex={-1}
              onclick={(e) => e.stopPropagation()}
              onchange={() => toggleModel(entry.model_id)}
            />
            <div class="min-w-0 flex-1">
              <span class="text-sm font-medium {existing ? 'text-quiet' : 'text-foreground'}">
                {entry.model_id}
              </span>
              {#if existing}
                <span class="ml-2 text-xs text-quiet">(already configured)</span>
              {:else}
                <span class="ml-2 text-xs text-muted">{formatMeta(entry)}</span>
              {/if}
              {#if entry.source || entry.confidence}
                <div class="mt-1 flex flex-wrap gap-1 text-[10px] uppercase tracking-[0.18em] text-quiet">
                  {#if entry.source}<span>{entry.source}</span>{/if}
                  {#if entry.confidence}<span>{entry.confidence}</span>{/if}
                </div>
              {/if}
            </div>
          </button>
        {/each}
      {/if}
    </div>
  {/snippet}

  {#snippet footer()}
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <span class="text-sm text-muted">
        {#if selectedCount > 0}
          {selectedCount} selected
        {:else}
          No models selected
        {/if}
      </span>
      <div class="flex gap-3">
        <Button variant="secondary" onclick={onclose}>Cancel</Button>
        <Button disabled={selectedCount === 0} onclick={handleAdd}>
          Add selected
        </Button>
      </div>
    </div>
  {/snippet}
</BlockingDialog>
