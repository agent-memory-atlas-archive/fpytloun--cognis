<script lang="ts">
  import type { Snippet } from 'svelte';
  let { onclick, label, children }: {
    onclick: () => void; label?: string; children: Snippet;
  } = $props();
</script>

<button type="button" aria-label={label}
  class="w-full rounded-lg border border-control-border bg-raised/50 p-4 text-left transition-colors hover:border-control-border hover:bg-raised/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
  {onclick}>
  {@render children()}
</button>
