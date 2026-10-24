<script lang="ts">
  let { custom = false, onChanged }: { custom?: boolean; onChanged: () => Promise<void> } = $props();
  import { onMount } from 'svelte';
  import { api, asApiError } from '$lib/api/client';
  import { applyProviderPresetDefaults, createProviderForm, providerFormToPayload } from '$lib/providers';
  import { recommendedRoutes } from '$lib/onboarding';
  import CompanionRouting from './CompanionRouting.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import type { LLMProvider, ModelRouting } from '$lib/types/api';

  let providers = $state<LLMProvider[]>([]);
  let routing = $state<ModelRouting>({} as ModelRouting);
  let providerId = $state('');
  let key = $state('');
  let busy = $state(false);
  let error = $state('');
  let notice = $state('');
  let loaded = $state(false);
  const selected = $derived(providers.find((provider) => provider.provider_id === providerId));
  const suggestions = $derived(selected ? recommendedRoutes(selected, routing) : {});
  const imageOptions = $derived(providers.filter((p) => p.status === 'active' && p.owner_email === 'system@cognis.local')
    .flatMap((p) => p.models.filter((m) => m.supports_image_generation).map((m) => ({
      value: m.model_id.startsWith(`${p.provider_id}/`) ? m.model_id : `${p.provider_id}/${m.model_id}`,
      label: `${m.display_name || m.model_id} · ${p.display_name}`
    }))));
  async function load() {
    const [list, routes] = await Promise.all([api.llmProviders.list(), api.modelRouting.get()]);
    providers = list.items;
    routing = routes;
    providerId ||= providers.find((p) => p.status === 'active' && p.owner_email === 'system@cognis.local')?.provider_id ?? '';
    loaded = true;
  }
  async function createOpenRouter() {
    busy = true; error = ''; notice = '';
    try {
      const form = createProviderForm();
      form.preset = 'openrouter';
      applyProviderPresetDefaults(form);
      form.display_name = 'OpenRouter starter';
      form.owner_scope = 'system';
      form.auth_mode = 'secret';
      // A fresh name avoids overwriting any existing provider's credentials.
      form.auth_secret_name = `openrouter_${crypto.randomUUID().replaceAll('-', '')}`;
      const discovered = await api.llmProviders.discoverModelsPreview({
        preset: form.preset, base_url: form.base_url, api_key: key
      });
      form.models = discovered.models;
      await api.secrets.upsert({ name: form.auth_secret_name, value: key, scope: 'system' });
      key = '';
      const provider = await api.llmProviders.create(providerFormToPayload(form));
      providerId = provider.provider_id;
      await load();
      notice = 'Provider saved. Review the proposed routes below before saving.';
    } catch (caught) { error = asApiError(caught).message; }
    finally { busy = false; }
  }
  async function discover() {
    if (!selected) return;
    busy = true; error = '';
    try {
      await api.llmProviders.discoverModels(selected.provider_id);
      await load();
      notice = 'Model catalog refreshed. Account access and generation still require a provider test.';
    } catch (caught) { error = asApiError(caught).message; }
    finally { busy = false; }
  }
  async function save() {
    busy = true; error = '';
    try {
      routing = await api.modelRouting.update({ ...routing });
      notice = 'Routes saved. Configuration checks do not prove credentials or embedding dimensions; verify them before finishing.';
      await onChanged();
    } catch (caught) { error = asApiError(caught).message; }
    finally { busy = false; }
  }
  async function test() {
    if (!selected) return;
    busy = true; error = '';
    try { notice = JSON.stringify(await api.llmProviders.test(selected.provider_id)); }
    catch (caught) { error = asApiError(caught).message; }
    finally { busy = false; }
  }
  onMount(() => { void load().catch((caught) => { error = asApiError(caught).message; }); });
</script>

<div class="space-y-4">
  <h2 class="text-lg font-semibold text-strong">{custom ? 'Custom system providers' : 'Providers and models'}</h2>
  <p class="text-sm text-muted">{custom ? 'Connect global providers, then choose the system models below. You can combine providers for chat, memory, safety checks, embeddings, and images.' : 'One OpenRouter API key can cover agent chat, Intaris, Mnemory, embeddings, and image generation. Charges and account limits apply. Global companion providers serve all users.'}</p>
  {#if !custom}
  <details>
    <summary class="cursor-pointer text-accent">Add an OpenRouter starter provider</summary>
    <div class="mt-3 space-y-3">
      <label class="block text-sm">OpenRouter API key
        <input class="mt-1 w-full rounded-lg border border-control-border bg-canvas p-2" type="password" autocomplete="off" bind:value={key} disabled={busy} />
      </label>
      <Button onclick={createOpenRouter} disabled={busy || !key.trim()}>Discover models and save provider</Button>
      <p class="text-xs text-muted">The key is encrypted in Cognis. Existing providers and routes are not replaced.</p>
    </div>
  </details>
  {/if}
  <p class="text-sm"><a class="text-accent underline" href="/settings?tab=providers">Manage providers in Settings →</a> Return to setup after saving. System providers must be global; agent-only providers can be private.</p>
  {#if error}<p role="alert" class="text-sm text-danger">{error}</p>{/if}
  {#if notice}<p role="status" class="break-words text-sm text-secondary">{notice}</p>{/if}
  {#if loaded}
    <label class="block text-sm">Provider for recommendations
      <select class="mt-1 w-full rounded-lg border border-control-border bg-canvas p-2" bind:value={providerId} disabled={busy}>
        <option value="">Choose a global provider</option>
        {#each providers.filter((p) => p.status === 'active' && p.owner_email === 'system@cognis.local') as provider}
          <option value={provider.provider_id}>{provider.display_name}</option>
        {/each}
      </select>
    </label>
    <div class="flex flex-wrap gap-2">
      <Button variant="secondary" onclick={discover} disabled={busy || !selected}>Refresh models</Button>
      <Button variant="secondary" onclick={test} disabled={busy || !selected}>Test provider (may incur cost)</Button>
    </div>
    {#if Object.keys(suggestions).length}
      <details open>
        <summary class="cursor-pointer text-sm">Recommended additions (existing routes stay unchanged)</summary>
        <ul class="mt-2 space-y-1 text-sm text-secondary">
          {#each Object.entries(suggestions) as [role, entry]}<li class="break-all">{role}: {entry.model}</li>{/each}
        </ul>
        <Button class="mt-3" variant="secondary" disabled={busy} onclick={() => { routing = { ...routing, ...Object.fromEntries(Object.entries(suggestions).map(([role, entry]) => [role, { ...entry, reasoning_effort: null }])) }; }}>Use these suggestions</Button>
      </details>
    {/if}
    <p class="text-sm text-muted">Recommended: GPT-OSS-20B for Lite, GPT-OSS-120B for Smart and memory extraction/retrieval. Jev is only for Intaris evaluation and requires a current Intaris image with EVALUATOR_BACKEND=auto. Otherwise use GPT-OSS-20B.</p>
    <CompanionRouting bind:routing {providers} />
    <p class="text-sm text-warning">Embeddings are required. Match the model's dimensions to both companion stores (Compose defaults: 1536). Do not change a populated store's embedding model without migration.</p>
    <label class="block text-sm">Image generation — optional, recommended for agent avatars
      <select class="mt-1 w-full rounded-lg border border-control-border bg-canvas p-2" value={routing.image_generation?.model ?? ''} onchange={(event) => { routing = { ...routing, image_generation: { model: event.currentTarget.value || null, reasoning_effort: null } }; }}>
        <option value="">Skip image generation</option>
        {#each imageOptions as model}<option value={model.value}>{model.label}</option>{/each}
      </select>
    </label>
    <p class="text-sm"><a href="/settings?tab=routing" class="text-accent">Choose agent/default model and advanced routes →</a> Codex can be used for the agent while companion models stay on OpenRouter or Groq.</p>
    <Button onclick={save} disabled={busy}>Save model routes</Button>
  {/if}
</div>
