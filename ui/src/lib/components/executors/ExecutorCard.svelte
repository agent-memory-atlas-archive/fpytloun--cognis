<script lang="ts">
  import { Monitor, Globe, Code, Brain, FileText, Plug, ChevronRight } from 'lucide-svelte';
  import { base } from '$app/paths';
  import { executorHealth, formatBytes, formatDuration, percentUsed } from '$lib/executors';
  import type { ExecutorConfig } from '$lib/types/api';
  import type { ResourceSample } from '$lib/executor-monitor';
  import ExecutorMiniChart from './ExecutorMiniChart.svelte';

  let { executor, history = [], onOpen } = $props<{
    executor: ExecutorConfig;
    history?: ResourceSample[];
    onOpen: () => void;
  }>();
  const snapshot = $derived(executor.resource_snapshot);
  const os = $derived((snapshot?.os ?? executor.runtime_metadata.platform?.os ?? '').toLowerCase());
  const platform = $derived(os === 'darwin' || os === 'macos' ? 'macOS' : os === 'linux' ? 'Linux' : os === 'windows' ? 'Windows' : 'Platform unknown');
  const platformLogo = $derived(platform === 'macOS' ? 'apple' : platform === 'Linux' ? 'linux' : platform === 'Windows' ? 'windows' : null);
  const health = $derived(executorHealth(executor));
  const stale = $derived(snapshot?.freshness?.stale === true || executor.runtime_state === 'offline' || executor.status !== 'active');
  const capabilities = [
    { key: 'browser', label: 'Browser', icon: Globe },
    { key: 'lsp', label: 'LSP', icon: Code },
    { key: 'documents', label: 'Documents', icon: FileText },
    { key: 'mcp', label: 'MCP', icon: Plug },
    { key: 'inference', label: 'Inference', icon: Brain }
  ];
  const gpu = $derived(snapshot?.accelerators?.[0]);
  const tone = $derived(health.state === 'healthy' ? 'text-success' : ['critical', 'offline', 'unavailable'].includes(health.state) ? 'text-danger' : health.state === 'unknown' ? 'text-muted' : 'text-warning');
</script>

<button type="button" onclick={onOpen} data-testid={`executor-card-${executor.executor_id}`}
  class="group flex min-w-0 flex-col rounded-2xl border border-separator bg-surface/40 p-5 text-left transition-colors hover:border-control-border hover:bg-surface/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
  <div class="flex items-start gap-3">
    <div class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-control-border/70 bg-canvas/60 text-secondary" title={platform}>
      {#if platformLogo}
        <img src={`${base}/platforms/${platformLogo}.svg`} alt={`${platform} logo`} width="26" height="26"
          class={`h-[26px] w-[26px] object-contain ${platformLogo === 'apple' ? 'invert' : ''}`} />
      {:else}<Monitor size={23} />{/if}
    </div>
    <div class="min-w-0 flex-1">
      <h3 class="truncate font-semibold text-foreground" title={executor.name}>{executor.name}</h3>
      <p class="mt-1 truncate text-xs text-quiet">{platform}{#if snapshot?.arch} · {snapshot.arch}{/if}</p>
    </div>
    <ChevronRight size={16} class="mt-1 shrink-0 text-quiet group-hover:text-secondary" />
  </div>
  <div class="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
    <span class={`inline-flex items-center gap-1.5 ${tone}`} title={health.detail}><span class="h-1.5 w-1.5 rounded-full bg-current"></span>{health.label}</span>
    {#if executor.is_default}<span class="text-muted">Default</span>{/if}
    {#if executor.shared}<span class="text-muted">Shared</span>{/if}
    <span class="ml-auto text-quiet">{snapshot?.runtime?.active_calls ?? '—'} {stale ? 'last active calls' : 'active calls'}</span>
  </div>
  <div class="mt-5 grid grid-cols-2 gap-5">
    <ExecutorMiniChart label="CPU" value={snapshot?.cpu?.utilization_percent ?? null} detail={snapshot?.cpu?.logical_cores ? `${snapshot.cpu.logical_cores} logical cores` : 'CPU not reported'} {history} metric="cpu" {stale} />
    <ExecutorMiniChart label={snapshot?.memory?.unified ? 'Unified memory' : 'Memory'} value={percentUsed(snapshot?.memory?.used_bytes, snapshot?.memory?.total_bytes)}
      detail={snapshot?.memory ? `${formatBytes(snapshot.memory.used_bytes)} / ${formatBytes(snapshot.memory.total_bytes)}` : 'Memory not reported'} {history} metric="memory" tone="text-violet-tone" {stale} />
  </div>
  {#if gpu}
    <div class="mt-4">
      <ExecutorMiniChart label="GPU" value={gpu.utilization_percent} detail={gpu.name ?? gpu.backend} {history} metric="gpu" tone="text-success" {stale} />
    </div>
  {/if}
  <div class="mt-auto pt-5">
  <div class="flex flex-wrap gap-x-4 gap-y-2 border-t border-separator pt-4">
    {#each capabilities as capability}
      {@const status = capability.key === 'lsp'
        ? executor.observed_capabilities?.lsp : executor.observed_capabilities?.components[capability.key]}
      {@const state = capability.key === 'inference' && !executor.local_inference_enabled ? 'disabled' : status?.state ?? 'unknown'}
      <span class={`inline-flex items-center gap-1.5 text-[11px] ${state === 'ready' ? 'text-secondary' : state === 'installable' ? 'text-warning' : 'text-quiet'}`}
        title={`${capability.label}: ${state}${status?.message ? ` — ${status.message}` : ''}`}>
        <capability.icon size={13} />{capability.label}
        <span class={`h-1 w-1 rounded-full ${state === 'ready' ? 'bg-success' : state === 'installable' ? 'bg-warning' : 'bg-muted'}`}></span>
      </span>
    {/each}
  </div>
  <div class="mt-4 flex items-center justify-between gap-2 text-[10px] text-quiet">
    <span>20 min · collected while open</span>
    <span>{snapshot?.freshness ? `${stale ? 'Last sample' : 'Updated'} ${formatDuration(snapshot.freshness.age_seconds)} ago` : 'Awaiting telemetry'}</span>
  </div>
  </div>
</button>
