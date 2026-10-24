<script lang="ts">
  import {
    capabilityStatusLabel,
    capabilityStatusTone,
    executorCapabilityFreshness
  } from '$lib/executors';
  import type { RuntimeCapabilityStatus, ExecutorConfig } from '$lib/types/api';

  let { executor } = $props<{ executor: ExecutorConfig }>();

  const report = $derived(executor.observed_capabilities);
  const freshness = $derived(executorCapabilityFreshness(report));
  type StatusEntry = [string, RuntimeCapabilityStatus];
  const statusEntries = (value: Record<string, RuntimeCapabilityStatus>): StatusEntry[] => Object.entries(value);
  const componentEntries = $derived(report ? statusEntries(report.components) : []);

  const runtimeEntries = $derived(report ? statusEntries(report.browser.runtimes) : []);
  const engineEntries = $derived(report ? statusEntries(report.browser.engines) : []);
  const channelEntries = $derived(report ? statusEntries(report.browser.channels) : []);
  const runtimeSupportEntries = $derived<StatusEntry[]>(report ? [
    ['officecli', report.officecli],
    ['mcp_launch', report.mcp_launch],
    ['git', report.git],
    ['node', report.node],
    ['uv', report.uv],
    ['lsp', report.lsp]
  ] : []);
  const DISPLAY_NAMES: Record<string, string> = {
    mcp: 'MCP',
    mcp_launch: 'MCP launch',
    officecli: 'OfficeCLI',
    lsp: 'LSP',
    uv: 'uv'
  };

  function statusText(status: RuntimeCapabilityStatus): string {
    return status.version ? `${capabilityStatusLabel(status.state)} · v${status.version}` : capabilityStatusLabel(status.state);
  }

  function formatObservedAt(value: string): string {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Time unknown' : date.toLocaleString();
  }

  function titleCase(value: string): string {
    return DISPLAY_NAMES[value] ?? value.replace(/[_-]+/g, ' ').replace(/\b\w/g, (character) => character.toUpperCase());
  }
</script>

<section
  class="space-y-4"
  aria-label={`Runtime capabilities for ${executor.name}`}
  data-testid="executor-capabilities-panel"
>
  <div class="flex flex-col gap-3 rounded-2xl border border-separator bg-canvas/45 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
    <div>
      <div class="flex flex-wrap items-center gap-2">
        <h3 class="text-sm font-semibold text-foreground">Runtime capabilities</h3>
        {#if report}
          <span class="rounded-full border border-control-border px-2 py-0.5 text-[10px] uppercase tracking-wider text-muted">
            schema v{report.schema_version}
          </span>
        {/if}
      </div>
      {#if report}
        <p class="mt-1 text-xs text-muted">
          Executor v{report.executor_version}
          {#if report.image_variant} · {titleCase(report.image_variant)} image{/if}
        </p>
      {:else}
        <p class="mt-1 text-xs text-muted">No capability report is available for this executor.</p>
      {/if}
    </div>
    {#if report}
      <div class="text-left text-xs text-muted sm:text-right">
        <p class={freshness.state === 'stale' ? 'text-warning' : ''}>{freshness.label}</p>
        <p class="mt-1 text-quiet">{formatObservedAt(report.observed_at)}</p>
      </div>
    {/if}
  </div>

  {#if report}
    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <article class="rounded-2xl border border-separator bg-canvas/55 p-4">
        <h4 class="text-xs font-semibold uppercase tracking-[0.18em] text-quiet">Browser runtimes</h4>
        <div class="mt-3 space-y-2">
          {#each runtimeEntries as [name, status]}
            <div class="flex items-center justify-between gap-3 text-sm">
              <span class="text-secondary">{titleCase(name)}</span>
              <span class={`rounded-full border px-2 py-0.5 text-[10px] ${capabilityStatusTone(status.state)}`} title={status.message}>{statusText(status)}</span>
            </div>
          {/each}
          {#if runtimeEntries.length === 0}<p class="text-xs text-quiet">Not reported</p>{/if}
        </div>
      </article>

      <article class="rounded-2xl border border-separator bg-canvas/55 p-4">
        <h4 class="text-xs font-semibold uppercase tracking-[0.18em] text-quiet">Browser engines & channels</h4>
        <div class="mt-3 space-y-2">
          {#each [...engineEntries, ...channelEntries] as [name, status]}
            <div class="flex items-center justify-between gap-3 text-sm">
              <span class="text-secondary">{titleCase(name)}</span>
              <span class={`rounded-full border px-2 py-0.5 text-[10px] ${capabilityStatusTone(status.state)}`} title={status.message}>{statusText(status)}</span>
            </div>
          {/each}
          {#if engineEntries.length === 0 && channelEntries.length === 0}<p class="text-xs text-quiet">Not reported</p>{/if}
        </div>
      </article>

      <article class="rounded-2xl border border-separator bg-canvas/55 p-4">
        <h4 class="text-xs font-semibold uppercase tracking-[0.18em] text-quiet">Runtime support</h4>
        <div class="mt-3 grid grid-cols-2 gap-2">
          {#each runtimeSupportEntries as [name, status]}
            <div class="rounded-xl border border-separator bg-surface/60 p-2">
              <p class="text-xs text-muted">{titleCase(name)}</p>
              <p class={`mt-1 text-xs ${capabilityStatusTone(status.state).split(' ').at(-1)}`}>{statusText(status)}</p>
              <p class="mt-1 line-clamp-2 text-[11px] text-quiet" title={status.message}>{status.message}</p>
            </div>
          {/each}
        </div>
      </article>
    </div>

    <div class="grid gap-3 lg:grid-cols-3">
      <article class="rounded-2xl border border-separator bg-canvas/55 p-4">
        <h4 class="text-xs font-semibold uppercase tracking-[0.18em] text-quiet">Configured desired tools</h4>
        <p class="mt-2 text-sm text-secondary">{report.desired_tools.length ? report.desired_tools.join(', ') : 'None reported'}</p>
      </article>
      <article class="rounded-2xl border border-separator bg-canvas/55 p-4">
        <h4 class="text-xs font-semibold uppercase tracking-[0.18em] text-quiet">Active observed tools</h4>
        <p class="mt-2 text-sm text-success">{report.observed_tools.length ? report.observed_tools.join(', ') : 'None reported'}</p>
      </article>
      <article class="rounded-2xl border border-separator bg-canvas/55 p-4">
        <h4 class="text-xs font-semibold uppercase tracking-[0.18em] text-quiet">Supported definitions</h4>
        <p class="mt-2 text-sm text-secondary">{report.supported_tools.length ? report.supported_tools.join(', ') : 'None reported'}</p>
      </article>
    </div>

    <details class="rounded-2xl border border-separator bg-canvas/40 px-4 py-3">
      <summary class="cursor-pointer text-xs font-semibold uppercase tracking-[0.18em] text-muted">Component summary</summary>
      <div class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {#each componentEntries as [name, status]}
          <div class="flex items-center justify-between gap-3 rounded-xl border border-separator bg-surface/50 px-3 py-2">
            <span class="text-sm text-secondary">{titleCase(name)}</span>
            <span class={`rounded-full border px-2 py-0.5 text-[10px] ${capabilityStatusTone(status.state)}`} title={status.message}>{capabilityStatusLabel(status.state)}</span>
          </div>
        {/each}
      </div>
    </details>
  {:else}
    <div class="rounded-2xl border border-dashed border-control-border bg-canvas/40 px-4 py-6 text-center">
      <p class="text-sm text-secondary">Runtime capability details are not available.</p>
      <p class="mt-1 text-xs text-quiet">Legacy, offline, or older executors can still be configured. Connect or update the executor to report its runtime.</p>
    </div>
  {/if}
</section>
