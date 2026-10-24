<script lang="ts">
  import RefreshCw from 'lucide-svelte/icons/refresh-cw';
  import type { WorkProjectionResponse } from '$lib/chat-v2/types';
  import { presentActivityLifecycle } from '$lib/work/activityLifecycle';

  let { materialization, onRetry } = $props<{
    materialization?: WorkProjectionResponse['materialization'];
    onRetry?: () => void;
  }>();
  const presentation = $derived(presentActivityLifecycle(materialization));
</script>

{#if presentation.kind !== 'none'}
  <div
    class={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
      presentation.kind === 'error'
        ? 'border-danger-border bg-danger-subtle text-danger'
        : presentation.kind === 'warning'
          ? 'border-warning-border bg-warning-subtle text-warning'
          : 'border-accent/20 bg-accent-subtle text-accent'
    }`}
    role={presentation.kind === 'error' ? 'alert' : 'status'}
    aria-live="polite"
    aria-busy={presentation.busy}
    data-testid={`activity-lifecycle-${materialization?.state}`}
  >
    {#if presentation.busy}
      <RefreshCw class="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden="true" />
    {/if}
    <span>{presentation.message}</span>
    {#if presentation.kind === 'error' && onRetry}
      <button type="button" class="ml-auto underline" onclick={onRetry}>Retry</button>
    {/if}
  </div>
{/if}
