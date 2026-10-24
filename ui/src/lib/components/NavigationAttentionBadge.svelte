<script lang="ts">
  import type { NavigationBadge } from '$lib/navigation-attention';

  let { badge, collapsed = false }: { badge?: NavigationBadge; collapsed?: boolean } = $props();
  const toneClass = $derived(
    badge?.tone === 'rose' ? 'bg-danger-subtle text-danger'
      : badge?.tone === 'amber' ? 'bg-warning-subtle text-warning'
        : 'bg-accent-subtle text-accent',
  );
  const dotClass = $derived(
    badge?.tone === 'rose' ? 'bg-danger'
      : badge?.tone === 'amber' ? 'bg-warning'
        : 'bg-accent',
  );
</script>

{#if badge && badge.count > 0}
  <span
    class={collapsed
      ? `absolute -right-1.5 -top-1.5 h-2 w-2 rounded-full ring-2 ring-separator ${dotClass}`
      : `ml-auto inline-flex min-w-5 shrink-0 items-center justify-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums ${toneClass}`}
    aria-label={badge.label}
    title={badge.label}
    data-testid={collapsed ? 'navigation-attention-dot' : 'navigation-attention-count'}
  >{#if !collapsed}{badge.count}{/if}</span>
{/if}
