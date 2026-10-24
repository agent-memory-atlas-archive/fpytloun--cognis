<script lang="ts">
  import { displayToolName } from '$lib/tools-display';

  let {
    toolName,
    argumentsDisplay,
    reasoning = null,
    risk = null,
    tone = 'sky'
  } = $props<{
    toolName: string | null | undefined;
    argumentsDisplay: Record<string, unknown> | null | undefined;
    reasoning?: string | null;
    risk?: string | null;
    tone?: 'sky' | 'emerald';
  }>();

  const rawPayload = $derived(
    argumentsDisplay ? JSON.stringify(argumentsDisplay, null, 2) : null
  );
  const primary = $derived.by(() => {
    if (!argumentsDisplay) return null;
    for (const key of ['action', 'command', 'url', 'path', 'file_path', 'query', 'script', 'description']) {
      const value = argumentsDisplay[key];
      if (typeof value === 'string' && value.trim()) return { key, value };
    }
    return null;
  });
  const accent = $derived(tone === 'emerald' ? 'text-success' : 'text-info');
  const scopeDetails = $derived(
    Object.entries(argumentsDisplay ?? {}).filter(([key, value]) =>
      ['agent_id', 'session_id', 'page_size', 'max_results', 'include_headers', 'operation', 'target'].includes(key)
      && (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean')
    )
  );
</script>

<div class={`mt-3 space-y-2 text-sm ${accent}`}>
  <div class="flex flex-wrap items-center gap-2">
    <span class="font-semibold">{displayToolName(toolName ?? 'escalated action')}</span>
    {#if risk}
      <span class="rounded-full border border-current/25 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide opacity-80">{risk} risk</span>
    {/if}
  </div>
  {#if primary}
    <pre class="overflow-x-auto rounded-xl bg-inset px-3 py-2 text-xs leading-5 text-foreground whitespace-pre-wrap break-words">{primary.value}</pre>
  {/if}
  {#if reasoning}
    <details open class="text-xs leading-5 opacity-80">
      <summary class="cursor-pointer font-medium">Why approval is required</summary>
      <p class="request-prose mt-1 text-foreground">{reasoning}</p>
    </details>
  {/if}
  {#if scopeDetails.length}
    <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
      {#each scopeDetails as [key, value]}
        <dt class="opacity-70">{key.replaceAll('_', ' ')}</dt>
        <dd class="break-words">{String(value)}</dd>
      {/each}
    </dl>
  {/if}
  {#if rawPayload}
    <details class="text-xs">
      <summary class="cursor-pointer font-medium opacity-80">Raw payload</summary>
      <pre class="mt-2 overflow-x-auto rounded-xl bg-inset px-3 py-2 leading-5 text-foreground whitespace-pre-wrap break-words">{rawPayload}</pre>
    </details>
  {/if}
</div>
