<script lang="ts">
  import { resourceChartPaths, type ResourceMetric, type ResourceSample } from '$lib/executor-monitor';

  interface Props {
    label: string;
    value: number | null;
    detail: string;
    history: ResourceSample[];
    metric: ResourceMetric;
    tone?: string;
    stale?: boolean;
  }
  let { label, value, detail, history, metric, tone = 'text-accent', stale = false }: Props = $props();
  const paths = $derived(resourceChartPaths(history, metric));
  const points = $derived(history.filter((sample: ResourceSample) => sample[metric] !== null).length);
</script>

<div class="min-w-0" class:opacity-50={stale}>
  <div class="flex items-baseline justify-between gap-2">
    <span class="text-xs text-muted">{label}</span>
    <span class="font-mono text-sm font-medium tabular-nums text-foreground">{value === null ? '—' : `${Math.round(value)}%`}</span>
  </div>
  <svg viewBox="0 0 240 54" preserveAspectRatio="none" class={`mt-2 h-14 w-full ${tone}`} role="img" aria-label={`${label}: ${value === null ? 'not reported' : `${Math.round(value)} percent`}. ${points} observed samples over the last 20 minutes.`}>
    <path d="M0,48 H240 M0,26 H240 M0,4 H240" stroke="currentColor" stroke-opacity="0.1" fill="none" />
    {#each paths as path}
      <path d={path} stroke="currentColor" stroke-width="2" fill="none" vector-effect="non-scaling-stroke" />
    {/each}
    {#if value !== null && history.length}
      <circle cx="238" cy={48 - Math.max(0, Math.min(100, value)) / 100 * 44} r="2.5" fill="currentColor" />
    {/if}
  </svg>
  <p class="mt-1 truncate text-[11px] text-quiet" title={detail}>{detail}</p>
</div>
