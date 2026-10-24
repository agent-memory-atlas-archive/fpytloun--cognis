<script lang="ts">
  import type { LLMProvider, ModelRouting, ModelRoutingEntry } from '$lib/types/api';
  import { thinkingEffortLabel } from '$lib/thinking';
  import { isChatModel, isDecisionModel } from '$lib/providers';

  let { routing = $bindable(), providers }: {
    routing: ModelRouting;
    providers: LLMProvider[];
  } = $props();

  const defaults = [
    { key: 'companion_lite', label: 'Lite model', description: 'Fast safety checks, memory extraction and search.' },
    { key: 'companion_smart', label: 'Smart model', description: 'Judge reviews, behavioral analysis and memory consolidation.' },
    { key: 'companion_embedding', label: 'Embedding model', description: 'Memory and semantic search vectors. Keep this model stable; changing it requires reindexing.' }
  ] as const;
  const overrides = [
    { key: 'intaris_evaluation', label: 'Intaris safety evaluation', parent: 'companion_lite' },
    { key: 'intaris_judge', label: 'Intaris judge', parent: 'companion_smart' },
    { key: 'intaris_analysis', label: 'Intaris analysis', parent: 'companion_smart' },
    { key: 'intaris_analysis_deep', label: 'Intaris deep analysis', parent: 'companion_smart' },
    { key: 'intaris_embedding', label: 'Intaris embeddings', parent: 'companion_embedding' },
    { key: 'mnemory_extraction', label: 'Mnemory extraction', parent: 'companion_lite' },
    { key: 'mnemory_retrieval', label: 'Mnemory retrieval', parent: 'companion_lite' },
    { key: 'mnemory_consolidation', label: 'Mnemory consolidation', parent: 'companion_smart' },
    { key: 'mnemory_maintenance', label: 'Mnemory maintenance', parent: 'companion_smart' },
    { key: 'mnemory_embedding', label: 'Mnemory embeddings', parent: 'companion_embedding' }
  ] as const;
  const globalProviders = $derived(providers.filter(
    (provider) => provider.owner_email === 'system@cognis.local' && provider.status === 'active'
  ));
  const options = $derived(globalProviders.flatMap((provider) =>
    provider.models.map((model) => ({
      value: model.model_id.startsWith(`${provider.provider_id}/`)
        ? model.model_id : `${provider.provider_id}/${model.model_id}`,
      label: `${model.display_name || model.model_id} · ${provider.display_name}`,
      embedding: !!model.supports_embedding,
      decision: isDecisionModel(model),
      chat: isChatModel(model),
      efforts: model.reasoning_efforts ?? []
    }))
  ));
  function eligible(key: string) {
    const embedding = key.includes('embedding');
    return options.filter((option) => embedding ? option.embedding : option.chat || (key === 'intaris_evaluation' && option.decision));
  }
  function entry(key: string): ModelRoutingEntry {
    return routing[key as keyof ModelRouting] ?? { model: null, reasoning_effort: null };
  }
  function change(key: string, model: string) {
    const decision = options.find((option) => option.value === model)?.decision;
    routing = { ...routing, [key]: { ...entry(key), model: model || null, ...(decision ? { reasoning_effort: 'default' } : {}) } };
  }
  function changeEffort(key: string, effort: string) {
    routing = { ...routing, [key]: { ...entry(key), reasoning_effort: effort || null } };
  }
  function efforts(key: string, parent?: string) {
    const model = entry(key).model || (parent ? entry(parent).model : null);
    return options.find((option) => option.value === model)?.efforts.filter((effort) => effort !== 'default') ?? [];
  }
  function isDecisionRoute(key: string, parent?: string) {
    const model = entry(key).model || (parent ? entry(parent).model : null);
    return options.find((option) => option.value === model)?.decision ?? false;
  }
</script>

{#snippet effortControl(key: string, label: string, parent?: string)}
  {@const available = efforts(key, parent)}
  {@const selected = entry(key).reasoning_effort ?? ''}
  <label class="block space-y-1 text-sm text-foreground">
    <span class="block">{label} thinking effort</span>
    <select value={selected} onchange={(event) => changeEffort(key, event.currentTarget.value)} class="w-full rounded-xl border border-control-border bg-canvas px-3 py-2">
      <option value="">{parent ? `Use ${parent.replace('companion_', '')} default` : 'Provider default'}</option>
      {#if parent}<option value="default">Provider default (ignore shared effort)</option>{/if}
      {#each available as effort}
        <option value={effort}>{thinkingEffortLabel(effort)}</option>
      {/each}
      {#if selected && selected !== 'default' && !available.includes(selected)}
        <option value={selected}>{thinkingEffortLabel(selected)} (unsupported by selected model)</option>
      {/if}
    </select>
    {#if available.length === 0}
      <span class="block text-xs text-muted">Select a model that supports thinking effort to set an explicit level.</span>
    {/if}
  </label>
{/snippet}

<section class="mt-6 space-y-4 border-t border-separator pt-5" aria-labelledby="companion-routing-title">
  <div>
    <h3 id="companion-routing-title" class="text-lg font-semibold text-strong">Intaris and Mnemory</h3>
    <p class="mt-1 text-sm text-muted">Shared across all users. Choose three defaults from enabled global providers; individual tasks inherit these choices.</p>
  </div>
  {#if globalProviders.length === 0}
    <p class="text-sm text-warning">Add a global provider in Settings → Providers before configuring companion inference. Private providers are not available to these services.</p>
  {/if}
  <div class="grid gap-4 md:grid-cols-3">
    {#each defaults as role}
      <div class="space-y-3">
      <label class="block space-y-2 text-sm text-foreground">
        <span class="block font-medium">{role.label}</span>
        <select value={entry(role.key).model ?? ''} onchange={(event) => change(role.key, event.currentTarget.value)} class="w-full rounded-xl border border-control-border bg-canvas px-3 py-2">
          <option value="">Not configured</option>
          {#each eligible(role.key) as option}
            <option value={option.value}>{option.label}</option>
          {/each}
        </select>
        <span class="block text-xs text-muted">{role.description}</span>
      </label>
      {#if role.key !== 'companion_embedding'}
        {@render effortControl(role.key, role.label)}
      {/if}
      </div>
    {/each}
  </div>
  <p class="text-xs text-muted">The lite and smart choices can use the same model. Companion inference remains unavailable until its required defaults are configured.</p>
  <p class="text-xs text-muted">Model and thinking effort inherit independently. These efforts are defaults: an explicit client request takes precedence. Provider default is not the same as Disabled.</p>
  <details class="space-y-3">
    <summary class="cursor-pointer text-sm text-foreground">Advanced task overrides</summary>
    <div class="grid gap-3 pt-3 md:grid-cols-2">
      {#each overrides as role}
        <div class="space-y-3">
        <label class="block space-y-1 text-sm text-foreground">
          <span class="block">{role.label}</span>
          <select value={entry(role.key).model ?? ''} onchange={(event) => change(role.key, event.currentTarget.value)} class="w-full rounded-xl border border-control-border bg-canvas px-3 py-2">
            <option value="">Use {role.parent.replace('companion_', '')} default</option>
            {#each eligible(role.key) as option}
              <option value={option.value}>{option.label}</option>
            {/each}
          </select>
        </label>
        {#if isDecisionRoute(role.key, role.parent)}
          <p class="text-xs text-muted">System One typed evaluation. Managed Intaris (EVALUATOR_BACKEND=auto) switches to Jev automatically; this model does not accept chat or thinking effort.</p>
        {:else if !role.key.includes('embedding')}
          {@render effortControl(role.key, role.label, role.parent)}
        {/if}
        </div>
      {/each}
    </div>
  </details>
</section>
