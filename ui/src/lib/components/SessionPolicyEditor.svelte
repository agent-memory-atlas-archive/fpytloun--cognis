<script lang="ts">
  import type { IntarisEvaluation } from '$lib/types/api';
  import { DEFAULT_INTARIS_EVALUATION } from '$lib/session-policy';
  let {
    evaluation = $bindable<IntarisEvaluation | ''>(''),
    showEvaluation = false,
    inheritedEvaluation = DEFAULT_INTARIS_EVALUATION,
    allowText = $bindable(''),
    denyText = $bindable(''),
    disabled = false,
    title = 'Session policies',
    help = 'Optional Intaris policies for this session. Enter one policy per line. Plain text is preferred; JSON objects are also accepted one per line.'
  } = $props<{
    allowText?: string;
    evaluation?: IntarisEvaluation | '';
    showEvaluation?: boolean;
    inheritedEvaluation?: IntarisEvaluation;
    denyText?: string;
    disabled?: boolean;
    title?: string;
    help?: string;
  }>();
</script>

<div class="rounded-2xl border border-separator bg-inset/40 p-4">
  <div class="mb-3">
    <p class="text-xs uppercase tracking-[0.25em] text-muted">{title}</p>
    <p class="mt-1 text-xs text-quiet">{help}</p>
  </div>
  {#if showEvaluation}
    <label class="mb-4 block space-y-2 text-sm font-medium text-foreground">
      <span>Intaris evaluation</span>
      <select bind:value={evaluation} {disabled} class="w-full rounded-xl border border-control-border bg-surface px-3 py-2 text-sm text-foreground focus:border-accent">
        <option value="">Inherit from agent ({inheritedEvaluation.replaceAll('_', ' ')})</option>
        <option value="legacy">Legacy</option>
        <option value="strict">Strict</option>
        <option value="balanced">Balanced</option>
        <option value="bounded_autonomy">Bounded autonomy</option>
      </select>
      <span class="block text-xs text-muted">Effective evaluation: {(evaluation || inheritedEvaluation).replaceAll('_', ' ')}. Existing restrictions and approval controls still apply.</span>
    </label>
  {/if}
  <div class="grid gap-3 md:grid-cols-2">
    <label class="space-y-2 text-sm font-medium text-foreground">
      <span>Allow policies</span>
      <textarea
        bind:value={allowText}
        disabled={disabled}
        class="min-h-[96px] w-full rounded-2xl border border-success-border bg-surface px-4 py-3 text-sm text-foreground placeholder:text-quiet focus:border-accent disabled:opacity-50"
        placeholder="Session is allowed to pass AWS SSO and grant CLI access"
      ></textarea>
      <span class="block text-xs text-quiet">Scope expansions and explicitly allowed support actions.</span>
    </label>
    <label class="space-y-2 text-sm font-medium text-foreground">
      <span>Deny policies</span>
      <textarea
        bind:value={denyText}
        disabled={disabled}
        class="min-h-[96px] w-full rounded-2xl border border-danger-border bg-surface px-4 py-3 text-sm text-foreground placeholder:text-quiet focus:border-accent disabled:opacity-50"
        placeholder="Session must not make write operations on environments reached through AWS SSM"
      ></textarea>
      <span class="block text-xs text-quiet">Hard restrictions. Deny policies win over allow policies.</span>
    </label>
  </div>
</div>
