<script lang="ts">
  import { QuietRefresh } from '$lib/quiet-refresh';

  let { error, scope = '', onRetry }: {
    error: string | null;
    scope?: string;
    onRetry: () => void;
  } = $props();
  let stale = $state(false);
  const freshness = new QuietRefresh(value => { stale = value; });

  $effect(() => { freshness.update(scope, error !== null); });
  $effect(() => () => freshness.dispose());
</script>

{#if stale}
  <p class="px-4 py-2 text-xs text-muted" data-testid="waiting-refresh-stale">
    Waiting updates are delayed.
    <button class="ml-1 underline hover:text-foreground" onclick={onRetry}>Retry</button>
  </p>
{/if}
