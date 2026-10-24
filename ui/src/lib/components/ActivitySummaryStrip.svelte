<script lang="ts">
  import DiffStat from './DiffStat.svelte';
  export type ActivitySummaryMetric = { id?: string; label: string; value: string | number; additions?: number | null; deletions?: number | null; tone?: 'default' | 'success' | 'warning' | 'danger' };
  let { metrics = [], onSelect }: { metrics?: ActivitySummaryMetric[]; onSelect?: (metric: ActivitySummaryMetric) => void } = $props();
</script>
<div class="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="activity-summary-strip" aria-label="Activity summary">
  {#each metrics as metric (metric.label)}
    {#if onSelect}
      <button type="button" class="min-w-0 rounded-lg border border-separator bg-surface/40 px-3 py-2 text-left hover:border-accent hover:bg-surface-hover" onclick={() => onSelect(metric)}>
        <span class="block truncate text-[10px] uppercase tracking-wide text-quiet">{metric.label}</span>
        <span class="mt-1 block text-sm font-medium text-foreground">{metric.value}</span>
        {#if metric.id === 'files'}<span class="mt-1 block"><DiffStat additions={metric.additions} deletions={metric.deletions} compact /></span>{/if}
      </button>
    {:else}
      <div class="min-w-0 rounded-lg border border-separator bg-surface/40 px-3 py-2 text-left">
        <span class="block truncate text-[10px] uppercase tracking-wide text-quiet">{metric.label}</span>
        <span class="mt-1 block text-sm font-medium text-foreground">{metric.value}</span>
        {#if metric.id === 'files'}<span class="mt-1 block"><DiffStat additions={metric.additions} deletions={metric.deletions} compact /></span>{/if}
      </div>
    {/if}
  {/each}
</div>
