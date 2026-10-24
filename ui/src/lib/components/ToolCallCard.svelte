<script lang="ts">
  import { isActiveToolStatus, type ToolCallTimelineItem } from '$lib/timeline-render-model';
  import LiveDots from '$lib/components/LiveDots.svelte';
  import { displayToolName } from '$lib/tools-display';

  let { item } = $props<{ item: ToolCallTimelineItem }>();
</script>

<article class="rounded-3xl border border-separator bg-surface/80 px-4 py-4 text-sm shadow-card">
  <div class="flex items-center justify-between gap-4">
    <div>
      <p class="text-xs font-medium uppercase tracking-[0.25em] text-muted">Tool call</p>
      <h3 class="mt-1 text-base font-semibold text-strong" title={item.toolName}>{displayToolName(item.displayToolName ?? item.toolName)}</h3>
    </div>
    <span class="rounded-full border border-control-border bg-raised px-3 py-1 text-xs font-medium text-foreground">
      {#if isActiveToolStatus(item.status)}
        <LiveDots inline={true} size="sm" tone="sky" />
        <span class="sr-only">Running</span>
      {:else}
        {item.status}
      {/if}
    </span>
  </div>
</article>
