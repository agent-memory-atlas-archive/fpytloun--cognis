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
  <p class="rounded-lg border border-warning-border p-2 text-xs text-warning">
    Not returned by this discovery snapshot. It can be partial; this model will not be removed.
  </p>
{:else if fields.length}
  <details class="rounded-lg border border-warning-border bg-warning-subtle p-3">
    <summary class="cursor-pointer text-sm text-warning">
      Registry drift: {fields.length} differing {fields.length === 1 ? 'field' : 'fields'}
    </summary>
    <p class="my-2 text-xs text-muted">
      Differences can be intentional overrides. Source: {registry.source || 'provider discovery / bundled registry'}.
      Resets change only the draft. Save the provider to apply them.
    </p>
    <ul class="space-y-2">
      {#each fields as field}
        <li class="rounded border border-warning-border p-2 text-xs">
          <strong class="text-warning">{field}</strong>
          <div class="break-words text-secondary">Configured: {showValue(model[field])}</div>
          <div class="break-words text-secondary">Registry: {showValue(registry[field])}</div>
          <button type="button" class="mt-1 text-accent underline"
            onclick={() => registry && onreset(resetModelDrift(model, registry, field))}>
            Reset {field}
          </button>
        </li>
      {/each}
    </ul>
    <button type="button" class="mt-3 rounded border border-warning-border px-3 py-1 text-sm text-warning"
      onclick={() => registry && onreset(resetModelDrift(model, registry))}>
      Reset all discovered fields for this model
    </button>
    <p class="mt-1 text-xs text-muted">Fields absent from discovery are unknown and remain unchanged.</p>
  </details>
{:else}
  {#if registry.context_window == null || registry.max_output_tokens == null}
    <p class="text-xs text-warning">Partial metadata; no differences in supplied registry fields.</p>
  {:else}
    <p class="text-xs text-success">Aligned with supplied registry fields. Unreported capabilities and prices remain unknown.</p>
  {/if}
{/if}
