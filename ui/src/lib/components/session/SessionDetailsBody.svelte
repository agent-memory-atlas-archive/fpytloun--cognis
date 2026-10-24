<script lang="ts">
  import ProviderHealthLine from '$lib/components/ProviderHealthLine.svelte';
  import { providerMonitoring } from '$lib/provider-monitor';
  import { thinkingEffortLabel } from '$lib/thinking';
  import Button from '$lib/components/ui/Button.svelte';
  import type { ContextUsage, GenerationPerformanceSnapshot, ProviderUsage, TokenUsage } from '$lib/types/api';
  import type { SessionDetailsProps } from './session-details-types';
  import ChevronDown from 'lucide-svelte/icons/chevron-down';
  import Star from 'lucide-svelte/icons/star';

  let {
    detail,
    sessionId = detail.session_id ?? detail.intaris_session_id,
    yoloMode = false,
    contextUsage = detail.context_usage,
    tokenUsage = detail.token_usage ?? detail.context_usage?.last_llm_usage,
    performance = detail.last_generation,
    onOpenIntaris,
    canStar = false,
    starred = false,
    starBusy = false,
    onToggleStar,
    canArchive = false,
    canDelete = false,
    archived = false,
    archiveBusy = false,
    deleteBusy = false,
    onArchive,
    onRestore,
    onDelete,
  }: SessionDetailsProps = $props();
  // Routes have no quota: show the provider actually serving this LLM session.
  const providerId = $derived(
    detail.inference_target?.provider_id
    ?? (contextUsage?.runtime_selection_revision != null
        && contextUsage.runtime_selection_revision >= (detail.runtime_selection?.revision ?? 0)
      ? contextUsage.provider_id : null)
    ?? detail.runtime_selection?.provider_id ?? contextUsage?.provider_id
  );
  const monitor = $derived(providerId ? $providerMonitoring[providerId] : null);
  const servingProviderId = $derived(
    detail.inference_target?.provider_id ?? contextUsage?.provider_id ?? performance?.provider_id
  );
  const servingModel = $derived(
    detail.inference_target?.model ?? contextUsage?.model ?? performance?.model
  );
  const providerUsage = $derived(monitor?.usage?.ok ? monitor.usage : null);
  const providerUsageError = $derived(monitor?.error ?? null);

  function providerUsageTitle(usage: ProviderUsage): string {
    switch (usage.source) {
      case 'anthropic_subscription_usage':
        return 'Claude subscription limits';
      case 'anthropic_rate_limit_headers':
        return 'Anthropic API rate limits';
      case 'chatgpt_codex_usage':
        return 'Codex subscription limits';
      default:
        return 'Provider usage limits';
    }
  }

  function fmt(value: number | null | undefined): string {
    return typeof value === 'number' ? value.toLocaleString() : 'Unknown';
  }

  function clampPercent(value: number | null | undefined): number {
    if (typeof value !== 'number' || !Number.isFinite(value)) return 0;
    return Math.min(100, Math.max(0, value));
  }

  function contextUsagePercent(usage: ContextUsage): number {
    if (usage.max_context_tokens <= 0) return 0;
    return clampPercent((usage.prompt_tokens / usage.max_context_tokens) * 100);
  }

  function contextBarColor(percent: number): string {
    if (percent > 95) return 'bg-danger';
    if (percent > 85) return 'bg-warning';
    if (percent > 65) return 'bg-warning';
    return 'bg-success';
  }

  function contextBudgetBars(usage: ContextUsage): Array<{ label: string; value: string; percent: number }> {
    const policy = usage.projection_policy;
    const budget = usage.available_prompt_tokens ?? usage.effective_prompt_budget;
    const targets: Array<[string, number | null | undefined]> = [
      ['Effective prompt budget', budget],
      ['Loop pressure', usage.loop_pressure_threshold],
      ['Steady target', policy?.steady_target_tokens],
      ['Within-turn burst', policy?.burst_target_tokens],
      ['Hard target', policy?.hard_prompt_tokens],
    ];
    return targets.map(([label, target]) => ({
      label,
      value: `${fmt(usage.prompt_tokens)} / ${fmt(target)}`,
      percent: typeof target === 'number' && target > 0
        ? clampPercent((usage.prompt_tokens / target) * 100)
        : 0,
    }));
  }

  function tokenUsageBars(usage: TokenUsage): Array<{ label: string; value: number; percent: number; color: string }> {
    const input = Math.max(0, usage.prompt_tokens);
    const output = Math.max(0, usage.completion_tokens);
    const total = Math.max(input + output, usage.total_tokens);
    return [
      { label: 'Input', value: input, percent: total > 0 ? (input / total) * 100 : 0, color: 'bg-accent' },
      { label: 'Output', value: output, percent: total > 0 ? (output / total) * 100 : 0, color: 'bg-violet-tone' },
    ];
  }

  function performanceRows(value: GenerationPerformanceSnapshot | null | undefined): Array<[string, string]> {
    if (!value) return [];
    const rows: Array<[string, string]> = [];
    if (value.is_local) {
      rows.push(
        ['Runtime', value.runtime ?? 'Unknown'],
        ['Executor', value.executor_name ?? value.executor_id ?? 'Unknown'],
      );
    }
    rows.push(
      ['Latency', typeof value.total_duration_seconds === 'number' ? `${value.total_duration_seconds.toFixed(2)} s` : 'Unknown'],
      ['First token', typeof value.time_to_first_token_seconds === 'number' ? `${value.time_to_first_token_seconds.toFixed(2)} s` : 'Unknown'],
      [value.is_local ? 'Tokens/s' : 'Output rate', typeof value.generation_tokens_per_second === 'number' ? value.generation_tokens_per_second.toFixed(1) : 'Unknown'],
    );
    return rows;
  }
</script>

<div data-testid="session-details-content">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div>
      <p class="text-[10px] font-semibold uppercase tracking-widest text-quiet">Session details</p>
      <p class="mt-1 break-all font-mono text-xs text-secondary">{sessionId}</p>
    </div>
    <div class="flex shrink-0 items-center gap-1.5">
      {#if canStar && onToggleStar}
        <button
          class={`inline-flex h-8 w-8 items-center justify-center rounded-lg border border-control-border transition hover:bg-raised ${starred ? 'text-warning hover:text-warning' : 'text-muted hover:text-foreground'}`}
          type="button"
          title={starred ? 'Unstar conversation' : 'Star conversation'}
          aria-label={starred ? 'Unstar conversation' : 'Star conversation'}
          disabled={starBusy}
          onclick={() => onToggleStar?.()}
          data-testid="conversation-info-star"
        >
          <Star class={`h-4 w-4 ${starred ? 'fill-current' : ''}`} />
        </button>
      {/if}
      {#if onOpenIntaris}
        <Button size="sm" variant="secondary" onclick={() => onOpenIntaris?.(detail.intaris_session_id)}>Open in Intaris</Button>
      {/if}
    </div>
  </div>
  {#if yoloMode}
    <div
      role="alert"
      data-testid="session-details-yolo-warning"
      class="mt-3 rounded-xl border border-warning-border bg-warning-subtle px-3 py-2 text-xs text-warning"
    >
      <strong class="font-bold uppercase tracking-wide">Yolo mode active</strong>
      <p class="mt-1">Dangerous: Intaris still evaluates and audits calls, but policy may allow evaluated denials. Task restrictions still apply.</p>
    </div>
  {/if}
  {#if detail.summary || detail.intention}
    {@const narrative = detail.summary ?? detail.intention ?? ''}
    <details class="group mt-3" data-testid="session-narrative">
      <summary class="flex min-w-0 cursor-pointer list-none items-center gap-2 text-left">
        <span class="shrink-0 text-[10px] font-semibold uppercase tracking-widest text-quiet">
          {detail.summary ? 'Summary' : 'Intention'}
        </span>
        <span class="min-w-0 flex-1 truncate text-xs text-muted group-open:hidden">{narrative}</span>
        <ChevronDown class="h-3.5 w-3.5 shrink-0 text-quiet transition group-open:rotate-180" />
      </summary>
      <p class="mt-2 whitespace-pre-wrap text-sm leading-6 text-foreground">{narrative}</p>
    </details>
  {/if}
  <div class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
    <span>Status: <span class="text-foreground">{detail.status}</span></span>
    <span>Calls: <span class="text-foreground">{detail.total_calls}</span></span>
    <span class="text-success">{detail.approved_count} approved</span>
    <span class="text-danger">{detail.denied_count} denied</span>
    <span class="text-accent">{detail.escalated_count} escalated</span>
  </div>
  {#if detail.runtime_selection}
    <section class="mt-3 rounded-2xl border border-accent/70 bg-accent-subtle p-3" data-testid="session-selected-runtime">
      <p class="text-[10px] font-semibold uppercase tracking-widest text-accent">Selected for next message</p>
      <dl class="mt-2 grid gap-2 text-xs sm:grid-cols-3">
        <div><dt class="text-quiet">Profile</dt><dd class="mt-0.5 text-foreground">{detail.runtime_selection.profile_id}</dd></div>
        <div><dt class="text-quiet">Model</dt><dd class="mt-0.5 text-foreground">{detail.runtime_selection.provider_id ? `${detail.runtime_selection.provider_id}/` : ''}{detail.runtime_selection.model ?? 'Provider default'}</dd></div>
        <div><dt class="text-quiet">Thinking</dt><dd class="mt-0.5 text-foreground">{detail.runtime_selection.reasoning_effort === null ? 'Inherit routing/provider configuration' : thinkingEffortLabel(detail.runtime_selection.reasoning_effort)}</dd><dd class="text-quiet">Source: {detail.runtime_selection.reasoning_effort_source.replaceAll('_', ' ')}</dd></div>
      </dl>
    </section>
  {/if}
  {#if servingProviderId}
    <div class="mt-3 text-xs text-muted" data-testid="session-serving-target">
      Serving / last used:
      <span class="text-foreground">{servingProviderId}/{servingModel ?? ''}</span>
      {#if detail.inference_target?.reason === 'fallback'}
        <span class="ml-2 text-warning">Fallback target</span>
      {/if}
    </div>
  {/if}
  {#if (canArchive && ((archived && onRestore) || (!archived && onArchive))) || (canDelete && onDelete)}
    <div class="mt-3 flex flex-wrap gap-2" aria-label="Conversation lifecycle actions">
      {#if canArchive}
        {#if archived && onRestore}
          <Button size="sm" variant="secondary" disabled={archiveBusy || deleteBusy} onclick={() => void onRestore?.()}>
            {archiveBusy ? 'Restoring…' : 'Restore'}
          </Button>
        {:else if onArchive}
          <Button size="sm" variant="secondary" disabled={archiveBusy || deleteBusy} onclick={() => void onArchive?.()}>
            {archiveBusy ? 'Archiving…' : 'Archive'}
          </Button>
        {/if}
      {/if}
      {#if canDelete && onDelete}
        <Button size="sm" variant="danger" disabled={archiveBusy || deleteBusy} onclick={() => void onDelete?.()}>
          {deleteBusy ? 'Deleting…' : 'Delete'}
        </Button>
      {/if}
    </div>
  {/if}
  <div class="mt-4 grid gap-3 lg:grid-cols-2">
  <section class="rounded-2xl border border-separator bg-canvas/50 p-3">
    <p class="text-[10px] font-semibold uppercase tracking-widest text-quiet">Context window</p>
    {#if contextUsage}
      {@const usagePercent = contextUsagePercent(contextUsage)}
      <div class="mt-2">
        <div class="mb-1.5 flex items-center justify-between gap-3 text-xs">
          <span class="text-secondary">Prompt usage</span>
          <span class="text-foreground">{fmt(contextUsage.prompt_tokens)} / {fmt(contextUsage.max_context_tokens)} <span class="text-quiet">({usagePercent.toFixed(0)}%)</span></span>
        </div>
        <div
          aria-label={`Context usage: ${usagePercent.toFixed(0)}%`}
          aria-valuemax="100"
          aria-valuemin="0"
          aria-valuenow={usagePercent}
          class="h-2 overflow-hidden rounded-full bg-raised"
          data-testid="session-context-usage-bar"
          role="progressbar"
        >
          <div class={`h-full rounded-full ${contextBarColor(usagePercent)}`} style={`width: ${usagePercent}%`}></div>
        </div>
        <p class="mt-2 text-xs text-quiet">
          Last context:
          {performance?.model ?? contextUsage.model}
          {contextUsage.agent_profile_id && contextUsage.agent_profile_id !== 'default' ? ` · profile ${contextUsage.agent_profile_id}` : ''}
        </p>
      </div>
    {:else}
      <p class="mt-2 text-xs text-quiet">Context usage unavailable.</p>
    {/if}

    {#if tokenUsage}
      {@const cacheReadTokens = tokenUsage.cache_read_input_tokens ?? tokenUsage.cached_tokens}
      <div class="mt-3 border-t border-separator pt-3" data-testid="session-token-usage">
        <div class="mb-2 flex items-center justify-between gap-3 text-xs">
          <p class="font-semibold uppercase tracking-widest text-quiet">Last call usage</p>
          <span class="text-secondary">{fmt(tokenUsage.total_tokens)} tokens</span>
        </div>
        <div class="flex h-2 overflow-hidden rounded-full bg-raised" aria-label={`Last call token usage: ${fmt(tokenUsage.prompt_tokens)} input and ${fmt(tokenUsage.completion_tokens)} output tokens`}>
          {#each tokenUsageBars(tokenUsage) as token}
            {#if token.percent > 0}
              <div class={token.color} style={`width: ${token.percent}%`}></div>
            {/if}
          {/each}
        </div>
        <div class="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs" data-testid="session-token-usage-stats">
          <span class="whitespace-nowrap text-accent">Input {fmt(tokenUsage.prompt_tokens)}</span>
          <span class="whitespace-nowrap text-violet-tone">Output {fmt(tokenUsage.completion_tokens)}</span>
          {#if cacheReadTokens}
            <span class="whitespace-nowrap text-success">Cache read {fmt(cacheReadTokens)}</span>
          {/if}
          {#if tokenUsage.cache_write_tokens ?? tokenUsage.cache_creation_input_tokens}
            <span class="whitespace-nowrap text-warning">Cache write {fmt(tokenUsage.cache_write_tokens ?? tokenUsage.cache_creation_input_tokens)}</span>
          {/if}
        </div>
      </div>
    {/if}
  </section>

  <section class="rounded-2xl border border-separator bg-canvas/50 p-3">
    {#if providerId}
      <div data-testid="session-provider-usage-limits">
        <ProviderHealthLine {providerId} compact={false} showName={false}
          heading={providerUsage ? providerUsageTitle(providerUsage) : 'Provider health'} />
      </div>
    {/if}
    {#if !providerUsage && performance}
      <p class="text-[10px] font-semibold uppercase tracking-widest text-quiet">{performance.is_local ? 'Runtime and performance' : 'Request performance'}</p>
      <dl class="mt-3 grid gap-2 text-xs">
        {#each performanceRows(performance) as row}
          <div><dt class="text-quiet">{row[0]}</dt><dd class="mt-0.5 text-foreground">{row[1]}</dd></div>
        {/each}
      </dl>
    {:else if !providerUsage && !providerId}
      <p class="text-[10px] font-semibold uppercase tracking-widest text-quiet">Provider usage</p>
      <p class="mt-2 text-xs text-quiet">Usage appears after the provider reports a completed call.</p>
    {/if}
    {#if providerUsageError}
      <p class="mt-2 text-xs text-quiet" data-testid="session-provider-usage-error">Usage limits unavailable: {providerUsageError}</p>
    {/if}
  </section>
  </div>

  <section class="mt-3 rounded-2xl border border-separator bg-canvas/50 p-3">
    <details class="group" data-testid="session-details-diagnostics">
      <summary class="cursor-pointer list-none text-xs font-medium text-accent hover:text-accent-hover">
        <span class="group-open:hidden">Show context &amp; runtime details</span>
        <span class="hidden group-open:inline">Hide context &amp; runtime details</span>
      </summary>
      <div class="mt-3 grid gap-3 sm:grid-cols-2">
        <div class="space-y-2">
          {#if contextUsage}
            {#each contextBudgetBars(contextUsage) as metric}
              <div class="rounded-xl border border-separator/70 bg-canvas/40 px-2.5 py-2">
                <div class="mb-1.5 flex items-center justify-between gap-3 text-xs">
                  <span class="text-muted">{metric.label}</span>
                  <span class="text-foreground">{metric.value}</span>
                </div>
                <div class="h-1.5 overflow-hidden rounded-full bg-raised">
                  <div class={`h-full rounded-full ${contextBarColor(metric.percent)}`} style={`width: ${metric.percent}%`}></div>
                </div>
              </div>
            {/each}
          {/if}
        </div>
        <dl class="grid content-start gap-2 text-xs">
          <div><dt class="text-quiet">Last model / provider</dt><dd class="mt-0.5 text-foreground">{performance?.model ?? contextUsage?.model ?? 'Unknown'} · {performance?.provider_name ?? performance?.provider_id ?? contextUsage?.provider_id ?? 'default'}</dd></div>
          <div><dt class="text-quiet">Last agent profile</dt><dd class="mt-0.5 text-foreground">{contextUsage?.agent_profile_id ?? 'Default'}</dd></div>
          <div><dt class="text-quiet">Projection budget</dt><dd class="mt-0.5 text-foreground">{fmt(contextUsage?.available_prompt_tokens ?? contextUsage?.effective_prompt_budget)} tokens</dd></div>
          <div><dt class="text-quiet">Provider</dt><dd class="mt-0.5 text-foreground">{contextUsage?.provider_id ?? 'default'}</dd></div>
          {#if contextUsage?.raw_prompt_tokens != null}
            <div><dt class="text-quiet">Raw prompt estimate</dt><dd class="mt-0.5 text-foreground">{fmt(contextUsage.raw_prompt_tokens)} tokens</dd></div>
          {/if}
          {#if contextUsage?.prompt_token_calibration}
            <div><dt class="text-quiet">Session calibration</dt><dd class="mt-0.5 text-foreground">×{contextUsage.prompt_token_calibration.applied_ratio.toFixed(3)} from {contextUsage.prompt_token_calibration.source_request_id}</dd></div>
          {:else}
            <div><dt class="text-quiet">Session calibration</dt><dd class="mt-0.5 text-foreground">No compatible calibration applied</dd></div>
          {/if}
          {#if contextUsage?.estimator_identity}
            <div><dt class="text-quiet">Estimator</dt><dd class="mt-0.5 break-all text-foreground">{contextUsage.estimator_identity}</dd></div>
          {/if}
        </dl>
      </div>
    </details>
  </section>
</div>
