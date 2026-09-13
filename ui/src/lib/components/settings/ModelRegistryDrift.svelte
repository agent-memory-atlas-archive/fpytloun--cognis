<script lang="ts">
  import type { ModelEntry } from '$lib/types/api';
  import { modelDrift, resetModelDrift } from '$lib/model-drift';

  let { model, registry, onreset } = $props<{
    model: ModelEntry;
    registry: ModelEntry | null;
    onreset: (updated: ModelEntry) => void;
  }>();
  const fields = $derived(modelDrift(model, registry));
  const showValue = (value: unknown) => value === undefined ? 'Not configured' : JSON.stringify(value);
</script>

{#if !registry}
  <p class="rounded-lg border border-amber-500/30 p-2 text-xs text-amber-200">
    Not returned by this discovery snapshot. It can be partial; this model will not be removed.
  </p>
{:else if fields.length}
  <details class="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
    <summary class="cursor-pointer text-sm text-amber-200">
      Registry drift: {fields.length} differing {fields.length === 1 ? 'field' : 'fields'}
    </summary>
    <p class="my-2 text-xs text-slate-400">
      Differences can be intentional overrides. Source: {registry.source || 'provider discovery / bundled registry'}.
      Resets change only the draft. Save the provider to apply them.
    </p>
    <ul class="space-y-2">
      {#each fields as field}
        <li class="rounded border border-amber-500/20 p-2 text-xs">
          <strong class="text-amber-100">{field}</strong>
          <div class="break-words text-slate-300">Configured: {showValue(model[field])}</div>
          <div class="break-words text-slate-300">Registry: {showValue(registry[field])}</div>
          <button type="button" class="mt-1 text-sky-300 underline"
            onclick={() => registry && onreset(resetModelDrift(model, registry, field))}>
            Reset {field}
          </button>
        </li>
      {/each}
    </ul>
    <button type="button" class="mt-3 rounded border border-amber-400/40 px-3 py-1 text-sm text-amber-100"
      onclick={() => registry && onreset(resetModelDrift(model, registry))}>
      Reset all discovered fields for this model
    </button>
    <p class="mt-1 text-xs text-slate-400">Fields absent from discovery are unknown and remain unchanged.</p>
  </details>
{:else}
  <p class="text-xs text-emerald-300">Aligned with supplied registry fields.</p>
{/if}
