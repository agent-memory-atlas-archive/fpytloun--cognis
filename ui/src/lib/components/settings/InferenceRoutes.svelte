<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api/client';
  import { defaultRecovery, type InferenceRoute, type InferenceRouteConfig } from '$lib/inference-routes';
  import type { LLMProvider } from '$lib/types/api';
  import { confirmAction } from '$lib/stores/confirm';
  import Button from '$lib/components/ui/Button.svelte';
  import Card from '$lib/components/ui/Card.svelte';
  import RouteTargetPicker from './RouteTargetPicker.svelte';
  import { useSectionConnectivity } from '$lib/connectivity-section.svelte';

  let { providers, onchange = () => {} }: {
    providers: LLMProvider[];
    onchange?: (routes: InferenceRoute[]) => void;
  } = $props();
  let routes = $state<InferenceRoute[]>([]);
  let editing = $state<InferenceRoute | null>(null);
  let draft = $state<InferenceRouteConfig | null>(null);
  let busy = $state(false);
  let error = $state('');
  // A failed route load is hidden while the global connection banner applies
  // and reloads when the connection is restored. Save/delete errors always show.
  let loadFailed = $state(false);
  const net = useSectionConnectivity({ hasError: () => loadFailed, retry: () => load() });
  const options = $derived(providers.flatMap(provider =>
    [...new Set([
      ...provider.models.map(model => model.model_id),
      ...(typeof provider.config?.default_model === 'string' ? [provider.config.default_model] : [])
    ])].map(modelId => ({
      value: `${provider.provider_id}/${modelId}`, modelId,
      providerId: provider.provider_id, label: `${provider.display_name} · ${modelId}`
    }))
  ));

  async function load() {
    try {
      routes = (await api.inferenceRoutes.list()).routes;
      onchange(routes);
      loadFailed = false;
    } catch (e) {
      loadFailed = true;
      error = e instanceof Error ? e.message : 'Unable to load routes';
    }
  }
  onMount(load);
  function edit(route: InferenceRoute | null) {
    editing = route;
    draft = route ? structuredClone($state.snapshot(route.config)) : {
      name: '', targets: [{ provider_id: '', model: '', priority: 0 }],
      recovery: {...defaultRecovery}
    };
    draft.recovery ??= {...defaultRecovery};
    error = '';
    loadFailed = false;
  }
  async function save() {
    if (!draft) return;
    if (draft.targets.some(target => !target.provider_id || !target.model)) {
      error = 'Choose a model for every target.';
      return;
    }
    busy = true; error = ''; loadFailed = false;
    try {
      if (editing) await api.inferenceRoutes.update(editing, draft);
      else await api.inferenceRoutes.create(draft);
      draft = null;
      await load();
    } catch (e) { error = e instanceof Error ? e.message : 'Unable to save route'; }
    finally { busy = false; }
  }
  async function remove(route: InferenceRoute) {
    if (!await confirmAction({
      title: `Delete ${route.reference}?`,
      message: 'Agents and system roles referencing this route will stop working until reconfigured.',
      confirmLabel: 'Delete route'
    })) return;
    try { await api.inferenceRoutes.remove(route); await load(); }
    catch (e) { error = e instanceof Error ? e.message : 'Unable to delete route'; }
  }
</script>

<Card class="p-5 space-y-4">
  <div class="flex items-center justify-between gap-3">
    <div><h2 class="text-lg font-semibold">Named inference routes</h2>
      <p class="text-sm text-muted">Sticky LLM sessions with provider fallback. Use <code>cognis/name</code> in agents, system roles, or proxy clients.</p>
    </div>
    <Button onclick={() => edit(null)} disabled={busy}>Add route</Button>
  </div>
  {#if error && !(loadFailed && net.hideErrors)}<p role="alert" class="text-sm text-danger">{error}</p>{/if}
  {#each routes as route (route.route_id)}
    <div class="flex items-center justify-between gap-3 border-t border-separator pt-3">
      <div><p class="font-mono text-sm">{route.reference}</p>
        <p class="text-xs text-muted">{route.owner_scope === 'user' ? 'Private' : 'Global'} · {route.config.targets.length} targets · revision {route.revision}</p>
      </div>
      <div class="flex gap-2"><Button onclick={() => edit(route)}>Edit</Button><Button onclick={() => remove(route)}>Delete</Button></div>
    </div>
  {/each}
  {#if draft}
    <form onsubmit={(e) => {e.preventDefault(); void save();}} class="space-y-4 border-t border-control-border pt-4">
      <label class="block text-sm">Route name
        <input required pattern={'[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}'} bind:value={draft.name} class="mt-1 block w-full rounded border border-control-border bg-canvas p-2" />
      </label>
      <p class="text-xs text-muted">Lower priority runs first. Equal priorities balance new sessions; established sessions keep their target.</p>
      <p class="text-xs text-muted">Routes with personal providers are private. Global routes and system roles require shared providers.</p>
      {#each draft.targets as target, index}
        <div class="grid grid-cols-[1fr_6rem_auto] items-end gap-2">
          <RouteTargetPicker {options} value={`${target.provider_id}/${target.model}`} label={`Target ${index + 1}`} disabled={busy}
              onchange={(value) => {
                const selected = options.find(o => o.value === value);
                if (selected) {
                  target.provider_id = selected.providerId; target.model = selected.modelId;
                  if (draft && index === 0 && !draft.name.trim()) {
                    draft.name = selected.modelId.replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^[^a-zA-Z0-9]+/, '').slice(0, 128);
                  }
                }
              }}
          />
          <label class="text-sm">Priority<input type="number" min="0" max="1000" required bind:value={target.priority} class="mt-1 block w-full rounded border border-control-border bg-canvas p-2" /></label>
          <Button type="button" disabled={draft.targets.length === 1} onclick={() => {if (draft) draft.targets.splice(index, 1);}}>Remove</Button>
        </div>
      {/each}
      <Button type="button" disabled={draft.targets.length >= 16} onclick={() => draft?.targets.push({provider_id:'', model:'', priority:1})}>Add target</Button>
      {#if draft.recovery}
        <details><summary class="cursor-pointer text-sm">Advanced recovery</summary>
          <div class="mt-3 grid gap-3 sm:grid-cols-2">
            {#each Object.keys(defaultRecovery) as rawKey}
              {@const key = rawKey as keyof typeof defaultRecovery}
              <label class="text-xs">{key.replaceAll('_', ' ')}
                <input type="number" min={key.startsWith('max_') ? 0 : 1} required bind:value={draft.recovery[key]} class="mt-1 block w-full rounded border border-control-border bg-canvas p-2" />
              </label>
            {/each}
          </div>
        </details>
      {/if}
      <div class="flex gap-2"><Button type="submit" disabled={busy}>Save route</Button><Button type="button" onclick={() => draft = null} disabled={busy}>Cancel</Button></div>
    </form>
  {/if}
</Card>
