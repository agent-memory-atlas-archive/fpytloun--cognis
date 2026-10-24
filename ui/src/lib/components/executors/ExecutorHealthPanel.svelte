<script lang="ts">
  import {
    executorHealth,
    formatBytes,
    formatDuration,
    percentUsed
  } from '$lib/executors';
  import type { ExecutorConfig } from '$lib/types/api';
  import ExecutorResourceMeter from './ExecutorResourceMeter.svelte';

  let { executor } = $props<{ executor: ExecutorConfig }>();

  const snapshot = $derived(executor.resource_snapshot);
  const health = $derived(executorHealth(executor));
  const healthTone = $derived(
      health.state === 'healthy'
        ? 'border-success-border bg-success-subtle text-success'
        : health.state === 'critical' || health.state === 'offline' || health.state === 'unavailable'
        ? 'border-danger-border bg-danger-subtle text-danger'
        : health.state === 'pressure' || health.state === 'stale'
          ? 'border-accent/30 bg-accent-subtle text-accent'
          : 'border-control-border bg-surface/70 text-secondary'
  );
</script>

<section class="space-y-4" aria-label={`Current health for ${executor.name}`} data-testid="executor-health-panel">
  <div class={`flex flex-col gap-3 rounded-2xl border px-4 py-3 sm:flex-row sm:items-center sm:justify-between ${healthTone}`}>
    <div>
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-sm font-semibold">{health.label}</span>
        {#if snapshot?.os || snapshot?.arch}
          <span class="text-xs opacity-70">
            {[snapshot.os, snapshot.arch].filter(Boolean).join(' · ')}
          </span>
        {/if}
      </div>
      <p class="mt-1 text-xs opacity-80">{health.detail}</p>
    </div>
    {#if snapshot?.freshness}
      <p class="shrink-0 text-xs opacity-70">
        Updated {formatDuration(snapshot.freshness.age_seconds)} ago
      </p>
    {/if}
  </div>

  {#if snapshot}
    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <article class="space-y-3 rounded-2xl border border-separator bg-canvas/55 p-4">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-quiet">Processor</p>
          <p class="mt-1 line-clamp-2 text-sm text-foreground">{snapshot.cpu?.model ?? 'Model not reported'}</p>
          <p class="mt-1 text-xs text-quiet">
            {snapshot.cpu?.physical_cores ?? '—'} physical · {snapshot.cpu?.logical_cores ?? '—'} logical cores
          </p>
        </div>
        <ExecutorResourceMeter
          label="CPU now"
          value={snapshot.cpu?.utilization_percent ?? null}
          detail={snapshot.cpu?.utilization_percent == null ? 'Not reported' : `${Math.round(snapshot.cpu.utilization_percent)}%`}
        />
      </article>

      <article class="space-y-3 rounded-2xl border border-separator bg-canvas/55 p-4">
        <div class="flex items-start justify-between gap-3">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.18em] text-quiet">
              {snapshot.memory?.unified ? 'Unified memory' : 'Memory'}
            </p>
            <p class="mt-1 text-sm text-foreground">
              {formatBytes(snapshot.memory?.used_bytes)} used
            </p>
          </div>
          {#if snapshot.memory?.unified}
            <span class="rounded-full border border-violet-border bg-violet-subtle px-2 py-1 text-[10px] font-medium uppercase tracking-wider text-violet-tone">
              CPU + GPU
            </span>
          {/if}
        </div>
        <ExecutorResourceMeter
          label="RAM now"
          value={percentUsed(snapshot.memory?.used_bytes, snapshot.memory?.total_bytes)}
          detail={`${formatBytes(snapshot.memory?.available_bytes)} available`}
        />
      </article>

      <article class="space-y-3 rounded-2xl border border-separator bg-canvas/55 p-4">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-quiet">Accelerator</p>
          {#if snapshot.accelerators == null}
            <p class="mt-1 text-sm text-muted">Not reported</p>
          {:else if snapshot.accelerators.length === 0}
            <p class="mt-1 text-sm text-muted">No accelerator detected</p>
          {:else}
            <div class="mt-2 space-y-3">
              {#each snapshot.accelerators as accelerator}
                <div class="space-y-2">
                  <div class="flex items-baseline justify-between gap-2">
                    <p class="truncate text-sm text-foreground">{accelerator.name ?? 'GPU'}</p>
                    <span class="text-[10px] uppercase tracking-wider text-quiet">{accelerator.backend}</span>
                  </div>
                  {#if snapshot.memory?.unified && accelerator.backend === 'metal'}
                    <p class="text-xs text-quiet">
                      Shares {formatBytes(accelerator.total_memory_bytes)} unified memory
                    </p>
                  {:else}
                    <ExecutorResourceMeter
                      label="GPU memory"
                      value={percentUsed(accelerator.used_memory_bytes, accelerator.total_memory_bytes)}
                      detail={`${formatBytes(accelerator.used_memory_bytes)} / ${formatBytes(accelerator.total_memory_bytes)}`}
                    />
                  {/if}
                  <ExecutorResourceMeter
                    label="GPU now"
                    value={accelerator.utilization_percent}
                    detail={accelerator.utilization_percent == null ? 'Not reported' : `${Math.round(accelerator.utilization_percent)}%`}
                  />
                </div>
              {/each}
            </div>
          {/if}
        </div>
      </article>

      <article class="space-y-3 rounded-2xl border border-separator bg-canvas/55 p-4">
        <div class="flex items-start justify-between gap-3">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.18em] text-quiet">Ollama</p>
            <p class="mt-1 text-sm text-foreground">
              {snapshot.ollama?.status === 'reachable'
                ? `Online${snapshot.ollama.version ? ` · v${snapshot.ollama.version}` : ''}`
                : snapshot.ollama?.status === 'unreachable'
                  ? 'Not reachable'
                  : 'Status unknown'}
            </p>
          </div>
          <span class={`mt-1 h-2.5 w-2.5 rounded-full ${snapshot.ollama?.status === 'reachable' ? 'bg-success' : 'bg-muted'}`} aria-hidden="true"></span>
        </div>
        <p class="text-xs text-muted">
          {snapshot.ollama?.installed_model_count ?? '—'} installed · {snapshot.ollama?.running_model_count ?? '—'} running
        </p>
        {#if snapshot.ollama?.running_models?.length}
          <div>
            <p class="text-[10px] font-medium uppercase tracking-wider text-quiet">Active local models</p>
            <div class="mt-1 flex flex-wrap gap-1">
              {#each snapshot.ollama.running_models as model}
                <span class="rounded-md border border-success-border bg-success-subtle px-2 py-1 font-mono text-[11px] text-success">{model}</span>
              {/each}
            </div>
          </div>
        {/if}
      </article>

      <article class="space-y-3 rounded-2xl border border-separator bg-canvas/55 p-4">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-quiet">Model storage</p>
          <p class="mt-1 text-sm text-foreground">
            {formatBytes(snapshot.ollama_model_store?.free_bytes)} free
          </p>
        </div>
        <ExecutorResourceMeter
          label="Disk used"
          value={percentUsed(
            snapshot.ollama_model_store?.total_bytes != null && snapshot.ollama_model_store.free_bytes != null
              ? snapshot.ollama_model_store.total_bytes - snapshot.ollama_model_store.free_bytes
              : null,
            snapshot.ollama_model_store?.total_bytes
          )}
          detail={snapshot.ollama_model_store?.total_bytes == null ? 'Not reported' : `${formatBytes(snapshot.ollama_model_store.total_bytes)} total`}
        />
      </article>

      <article class="space-y-3 rounded-2xl border border-separator bg-canvas/55 p-4">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-quiet">Executor runtime</p>
          <p class="mt-1 text-sm text-foreground">
            {snapshot.runtime?.active_calls ?? '—'} active call{snapshot.runtime?.active_calls === 1 ? '' : 's'}
          </p>
        </div>
        <dl class="grid grid-cols-2 gap-2 text-xs">
          <div>
            <dt class="text-quiet">Uptime</dt>
            <dd class="mt-1 text-secondary">{formatDuration(snapshot.runtime?.uptime_seconds)}</dd>
          </div>
          <div>
            <dt class="text-quiet">State</dt>
            <dd class="mt-1 capitalize text-secondary">{snapshot.runtime?.state ?? executor.runtime_state}</dd>
          </div>
        </dl>
      </article>
    </div>
  {:else}
    <div class="rounded-2xl border border-dashed border-control-border bg-canvas/40 px-4 py-6 text-center">
      <p class="text-sm text-secondary">Current hardware details are not available.</p>
      <p class="mt-1 text-xs text-quiet">Reconnect or update this executor to collect a current snapshot.</p>
    </div>
  {/if}
  <div class="flex justify-end">
    <a
      href="/local-models"
      class="inline-flex min-h-10 items-center rounded-xl px-3 text-xs font-medium text-accent transition hover:bg-accent-subtle hover:text-accent-hover"
    >
      Plan a local model for this hardware →
    </a>
  </div>
</section>
