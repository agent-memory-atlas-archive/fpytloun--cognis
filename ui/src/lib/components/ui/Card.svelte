<script lang="ts">
  import type { Snippet } from 'svelte';

  import { cn } from '$lib/utils';

  let { class: className = '', children } = $props<{ class?: string; children?: Snippet }>();
</script>

<div class={cn('primitive-card rounded-3xl border shadow-card', className)}>
  {@render children?.()}
</div>
