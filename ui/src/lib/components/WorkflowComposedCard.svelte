<script lang="ts">
  import Badge from '$lib/components/ui/Badge.svelte';
  import type { WorkflowComposedTimelineItem } from '$lib/timeline-render-model';

  let { item } = $props<{ item: WorkflowComposedTimelineItem }>();
</script>

<article class="rounded-3xl border border-cyan-border bg-cyan-subtle px-4 py-4 text-sm text-foreground shadow-card">
  <div class="flex flex-wrap items-center gap-2">
    <p class="font-semibold text-strong">Workflow composed</p>
    <Badge class="border-cyan-border bg-cyan-subtle text-cyan-tone">{item.lifecycle}</Badge>
    {#if item.taskId}
      <a href="/tasks/{item.taskId}" class="inline-flex">
        <Badge class="border-control-border bg-surface/70 text-accent transition hover:border-accent hover:text-accent-hover">task</Badge>
      </a>
    {:else if item.scheduleId}
      <Badge class="border-control-border bg-surface/70 text-secondary">schedule</Badge>
    {/if}
  </div>
  <p class="mt-2 text-base font-medium text-strong">{item.workflowName}</p>
  <p class="mt-1 break-all text-xs text-secondary">{item.workflowId}</p>
  {#if item.steps.length > 0}
    <div class="mt-3 flex flex-wrap gap-2 text-xs text-cyan-tone">
      {#each item.steps as step}
        <span class="rounded-full border border-cyan-border bg-cyan-subtle px-2.5 py-1">{step}</span>
      {/each}
    </div>
  {/if}
</article>
