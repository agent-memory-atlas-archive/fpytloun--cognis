<script lang="ts">
  import type { Snippet } from 'svelte';
  let {
    title,
    text = '',
    details = '',
    tone = 'info',
    active = false,
    actionRequired = false,
    code = null,
    action
  } = $props<{
    title: string;
    text?: string;
    details?: string;
    tone?: 'info' | 'warning' | 'error';
    active?: boolean;
    actionRequired?: boolean;
    code?: string | null;
    action?: Snippet;
  }>();

  const palette = $derived(
    tone === 'error'
      ? 'border-danger-border bg-danger-subtle text-danger'
      : tone === 'warning'
        ? 'border-warning-border bg-warning-subtle text-warning'
        : 'border-control-border bg-surface/70 text-secondary'
  );
  const dot = $derived(
    tone === 'error' ? 'bg-danger' : tone === 'warning' ? 'bg-warning' : 'bg-muted'
  );
  const summary = $derived.by(() => {
    const normalized = text.trim().replace(/\s+/g, ' ');
    if (normalized === title.trim()) return '';
    return normalized;
  });
  const fullDetails = $derived(details.trim() || text.trim());
  const normalizedDetails = $derived(fullDetails.replace(/\s+/g, ' '));
  const displayedText = $derived(summary || title.trim().replace(/\s+/g, ' '));
  const showDetails = $derived(
    Boolean(fullDetails) && (normalizedDetails !== displayedText || Boolean(code))
  );
</script>

<article
  class={`mx-auto w-full min-w-0 border text-xs ${palette} ${actionRequired || tone === 'error' ? 'max-w-2xl rounded-2xl px-4 py-3 shadow-card' : 'max-w-2xl rounded-xl px-3 py-2'}`}
  role={tone === 'error' ? 'alert' : active ? 'status' : undefined}
>
  <div class="flex items-start gap-2.5">
    <span class={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${dot} ${active ? 'animate-pulse' : ''}`} aria-hidden="true"></span>
    <div class="min-w-0 flex-1">
      <div class="flex flex-wrap items-center gap-2">
        <p class="min-w-0 font-semibold [overflow-wrap:anywhere]">{title}</p>
        {#if code}
          <code class="min-w-0 rounded bg-inset px-1.5 py-0.5 text-[11px] [overflow-wrap:anywhere]">{code}</code>
        {/if}
      </div>
      {#if summary}
        <!-- anywhere (not break-word) also shrinks min-content, so an
             unbreakable token cannot widen the timeline. -->
        <p class="mt-1 whitespace-pre-line leading-5 opacity-90 [overflow-wrap:anywhere]">{summary}</p>
      {/if}
      {#if showDetails}
        <details class="mt-2">
          <summary class="cursor-pointer select-none font-medium opacity-75">Details</summary>
          <pre class="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-inset p-3 font-mono text-[11px] leading-5 [overflow-wrap:anywhere]">{fullDetails}</pre>
        </details>
      {/if}
      {#if action}
        {@render action()}
      {/if}
    </div>
  </div>
</article>
