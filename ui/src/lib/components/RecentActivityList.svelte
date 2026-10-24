<script lang="ts">
  export type RecentActivityItem = { id: string; title: string; detail?: string; timestamp?: string };
  let { items = [], onSelect }: { items?: RecentActivityItem[]; onSelect?: (item: RecentActivityItem) => void } = $props();
</script>
<ol class="divide-y divide-separator" data-testid="recent-activity-list">
  {#each items as item (item.id)}
    <li><button type="button" class="w-full min-w-0 px-2 py-2 text-left hover:bg-surface-hover" onclick={() => onSelect?.(item)}>
      <span class="block truncate text-sm text-foreground">{item.title}</span>
      {#if item.detail}<span class="block truncate text-xs text-quiet">{item.detail}</span>{/if}
    </button></li>
  {/each}
</ol>
