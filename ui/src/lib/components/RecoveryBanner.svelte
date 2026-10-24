<script lang="ts">
  import type { Snippet } from 'svelte';
  import Button from '$lib/components/ui/Button.svelte';
  let { message, actionLabel = 'Retry', onRetry, busy = false, children } = $props<{
    message: string;
    actionLabel?: string;
    onRetry: () => void;
    busy?: boolean;
    children?: Snippet;
  }>();
</script>

<div role="alert" class="rounded-2xl border border-danger-border bg-danger-subtle px-3 py-3 text-sm text-danger" data-testid="recovery-banner">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <p class="min-w-0 flex-1 whitespace-pre-wrap break-words">{message}</p>
    <Button size="sm" variant="secondary" disabled={busy} onclick={onRetry}>{actionLabel}</Button>
  </div>
  {#if children}{@render children()}{/if}
</div>
