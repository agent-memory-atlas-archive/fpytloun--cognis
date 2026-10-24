<script lang="ts">
  import { onMount } from 'svelte';
  import { api, asApiError } from '$lib/api/client';
  import { applyProviderPresetDefaults, createProviderForm, providerFormToPayload } from '$lib/providers';
  import { starterRouting } from '$lib/onboarding-setup';
  import OnboardingModelOptions from './OnboardingModelOptions.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import ProviderPresetIcon from './ProviderPresetIcon.svelte';
  import OnboardingAgentProviders from './OnboardingAgentProviders.svelte';
  import type { LLMProvider } from '$lib/types/api';

  let { onChanged, onContinue }: { onChanged: () => Promise<void>; onContinue: () => void } = $props();
  let key = $state('');
  let images = $state(true);
  let busy = $state(false);
  let loading = $state(true);
  let error = $state('');
  let provider = $state<LLMProvider | null>(null);
  let advanced = $state(false);
  let preset = $state<'openrouter' | 'custom' | null>(null);
  let providers = $state<LLMProvider[]>([]);
  async function continueCustom() {
    busy = true; error = '';
    try {
      const diagnostics = await api.system.diagnostics();
      if (!diagnostics.readiness.agent_model_configured || !diagnostics.readiness.companion_routes_configured) {
        throw new Error('Finish configuring the required system and default agent models before continuing.');
      }
      await onChanged(); onContinue();
    } catch (caught) { error = asApiError(caught).message; }
    finally { busy = false; }
  }
  async function load() {
    const { items } = await api.llmProviders.list();
    providers = items;
    const global = items.filter((p) => p.status === 'active' && p.owner_email === 'system@cognis.local');
    provider = global.find((p) => p.config.preset === 'openrouter') ?? global[0] ?? null;
    if (!preset && provider) preset = provider.config.preset === 'openrouter' ? 'openrouter' : 'custom';
  }
  async function connect() {
    busy = true; error = '';
    try {
      if (key.trim()) {
        const form = createProviderForm();
        form.preset = 'openrouter';
        applyProviderPresetDefaults(form);
        form.display_name = 'OpenRouter starter';
        form.owner_scope = 'system';
        form.auth_mode = 'secret';
        form.auth_secret_name = `openrouter_${crypto.randomUUID().replaceAll('-', '')}`;
        const discovered = await api.llmProviders.discoverModelsPreview({
          preset: form.preset, base_url: form.base_url, api_key: key.trim()
        });
        form.models = discovered.models;
        form.default_model = discovered.models.find((entry) => entry.model_id === 'openai/gpt-oss-120b' && entry.supports_tools)?.model_id ?? '';
        if (!form.default_model || !discovered.models.some((entry) => entry.supports_embedding && /(^|\/)text-embedding-3-small$/.test(entry.model_id))) {
          throw new Error('The recommended models are unavailable. Choose your provider and models in Advanced options.');
        }
        await api.secrets.upsert({ name: form.auth_secret_name, value: key.trim(), scope: 'system' });
        provider = await api.llmProviders.create(providerFormToPayload(form));
        key = '';
      }
      if (!provider) throw new Error('Enter your OpenRouter API key to connect.');
      if (provider.config.preset === 'openrouter') {
        const test = await api.llmProviders.test(provider.provider_id);
        if (!test.ok) throw new Error(test.error_detail || 'Could not connect. Check your provider key and account balance, then retry.');
      }
      const current = await api.modelRouting.get();
      await api.modelRouting.update({ ...starterRouting(provider, current, images) });
      await onChanged();
      onContinue();
    } catch (caught) { error = asApiError(caught).message; }
    finally { busy = false; }
  }
  onMount(() => {
    void load().catch((caught) => { error = asApiError(caught).message; }).finally(() => { loading = false; });
  });
</script>

<div class="space-y-6">
  <div>
    <h1 class="text-2xl font-semibold text-strong">Configure LLM provider</h1>
    <p class="mt-3 text-sm leading-6 text-muted">Cognis can use multiple providers and models. Some models are required for memory, safety checks, and other system features. OpenRouter is the simplest start: one key, with the best-fit models selected for you.</p>
  </div>
  {#if loading}
    <p class="text-sm text-muted" role="status">Loading your providers…</p>
  {:else}
    <div class="grid gap-3 sm:grid-cols-2" aria-label="System provider presets">
      {#each [{ id: 'openrouter', name: 'OpenRouter', description: 'Recommended · automatic model setup' }, { id: 'custom', name: 'Custom (advanced)', description: 'Choose your own providers and models' }] as option}
        <button type="button" disabled={busy} aria-pressed={preset === option.id} class="rounded-xl border p-4 text-left transition-colors {preset === option.id ? 'border-accent bg-accent-subtle' : 'border-control-border hover:border-border-strong'}" onclick={() => { preset = option.id as 'openrouter' | 'custom'; key = ''; error = ''; }}>
          <div class="flex items-center gap-3"><ProviderPresetIcon preset={option.id} /><strong class="text-strong">{option.name}</strong></div>
          <p class="mt-3 text-xs leading-5 text-muted">{option.description}</p>
        </button>
      {/each}
    </div>
    {#if preset === 'openrouter'}
    {#if provider?.config.preset === 'openrouter'}
      <p class="rounded-lg bg-success-subtle p-3 text-sm text-success">Using {provider.display_name}. Your existing model choices will be kept.</p>
    {:else}
      <label for="setup-provider-key" class="block text-sm font-medium text-foreground">OpenRouter API key</label>
      <input id="setup-provider-key" class="!mt-2 w-full rounded-lg border border-control-border bg-canvas px-3 py-3 text-sm" type="password" placeholder="Paste your API key" autocomplete="off" bind:value={key} disabled={busy} />
      <p class="!mt-2 text-xs text-muted">One key is enough. <a class="text-accent underline" href="https://openrouter.ai/keys" target="_blank" rel="noreferrer">Get an OpenRouter key ↗</a></p>
    {/if}
    <label class="flex items-start gap-3 text-sm text-foreground">
      <input type="checkbox" class="mt-1" bind:checked={images} disabled={busy} />
      <span>Enable image generation <span class="text-muted">(recommended)</span><span class="mt-1 block text-xs text-muted">Create an avatar for your assistant in the last step.</span></span>
    </label>
    <p class="text-xs leading-5 text-muted">Your key is stored securely. Connecting runs a small AI test; your provider charges for usage, including images. Existing settings are kept.</p>
    {#if error}<p role="alert" class="text-sm text-danger">{error}</p>{/if}
    <Button onclick={connect} disabled={busy || (provider?.config.preset !== 'openrouter' && !key.trim())}>{busy ? 'Connecting…' : provider?.config.preset === 'openrouter' ? 'Continue' : 'Connect and continue'}</Button>
    <details bind:open={advanced} class="border-t border-separator pt-4">
      <summary class="cursor-pointer text-sm text-muted">Advanced options</summary>
      {#if advanced}<div class="mt-5"><OnboardingModelOptions onChanged={async () => { await load(); await onChanged(); }} /></div>{/if}
    </details>
    {:else if preset === 'custom'}
      <OnboardingModelOptions custom onChanged={async () => { await load(); await onChanged(); }} />
      <p class="text-xs leading-5 text-muted">Configure the required system routes above. They are separate from your agent’s provider and model.</p>
      {#if error}<p role="alert" class="text-sm text-danger">{error}</p>{/if}
      <Button onclick={continueCustom} disabled={busy || !provider}>Continue</Button>
    {/if}
    <OnboardingAgentProviders {providers} onChanged={load} />
  {/if}
</div>
