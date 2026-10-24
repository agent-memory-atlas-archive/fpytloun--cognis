<script lang="ts">
  import { onMount } from 'svelte';
  import { api, asApiError } from '$lib/api/client';
  import Button from '$lib/components/ui/Button.svelte';
  import { executorDegradedDetails, executorRuntimeLabel } from '$lib/executors';
  import { auth } from '$lib/stores/auth';
  import type { ExecutorConfig } from '$lib/types/api';

  let { executorId, initialExecutor = null, onUpdated = () => undefined, onChanged = () => undefined } = $props<{
    executorId: string;
    initialExecutor?: ExecutorConfig | null;
    onUpdated?: (executor: ExecutorConfig) => void;
    onChanged?: () => void | Promise<void>;
  }>();
  let executor = $state<ExecutorConfig | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let notice = $state<string | null>(null);
  const canRetry = $derived(executor && executor.executor_type === 'websocket'
    && executor.status === 'active' && executor.available
    && $auth.user && (executor.shared
      ? $auth.user.role === 'admin'
      : executor.owner_email === $auth.user.email));
  const details = $derived(executor ? executorDegradedDetails(executor) : []);
  $effect(() => { if (initialExecutor) executor = initialExecutor; });

  async function refresh(): Promise<void> {
    if (busy) return;
    busy = true;
    error = null;
    try {
      executor = await api.executor.get(executorId);
      onUpdated(executor);
    } catch (caught) {
      error = asApiError(caught).message;
    } finally {
      busy = false;
    }
  }

  async function retry(): Promise<void> {
    if (busy || !canRetry) return;
    busy = true;
    error = null;
    notice = null;
    try {
      executor = await api.executor.reconfigure(executorId);
      onUpdated(executor);
      notice = 'Configuration retry requested. Refresh status to check the result.';
      await onChanged();
    } catch (caught) {
      error = asApiError(caught).message;
    } finally {
      busy = false;
    }
  }

  onMount(() => { if (!initialExecutor) void refresh(); });
</script>

<section class="min-w-0 space-y-2 rounded-xl border border-control-border bg-canvas/50 p-3 text-xs" aria-label="Executor runtime diagnostics">
  <div class="flex flex-wrap items-center justify-between gap-2">
    <p class="font-medium">Runtime diagnostics{executor ? ` — ${executorRuntimeLabel(executor)}` : ''}</p>
    <div class="flex flex-wrap gap-2">
      <Button size="sm" variant="secondary" disabled={busy} onclick={() => void refresh()}>Refresh status</Button>
      {#if canRetry}
        <Button size="sm" variant="secondary" disabled={busy || executor?.runtime_state === 'reconfiguring'} onclick={() => void retry()}>Retry configuration</Button>
      {/if}
    </div>
  </div>
  {#if busy}<p role="status">Loading executor status…</p>{/if}
  {#if error}<p role="alert" class="text-danger">{error}</p>{/if}
  {#if notice}<p role="status">{notice}</p>{/if}
  {#if executor}
    <p>Desired v{executor.desired_config_version}, applied v{executor.applied_config_version}</p>
    {#each details as detail}
      <p class="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{detail}</p>
    {:else}
      <p>No detailed runtime failures reported.</p>
    {/each}
    {#if canRetry}
      <p class="text-muted">Retry reinitializes all configured MCP servers. Settings are unchanged. An offline executor applies the request when it reconnects.</p>
    {/if}
  {/if}
</section>
