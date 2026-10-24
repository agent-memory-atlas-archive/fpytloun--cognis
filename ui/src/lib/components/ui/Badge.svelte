<script lang="ts">
  import type { Snippet } from 'svelte';

  import { cn } from '$lib/utils';

  let { class: className = '', children } = $props<{ class?: string; children?: Snippet }>();
</script>

<span class={cn('primitive-badge inline-flex items-center rounded-full border border-control-border px-2.5 py-1 text-xs font-medium', className)}>
  {@render children?.()}
</span>
