<script lang="ts">
  import { onMount } from 'svelte';
  import { auth } from '$lib/stores/auth';
  import { api, asApiError } from '$lib/api/client';
  import { applyProviderPresetDefaults, createProviderForm, providerFormToPayload, providerFormToUpdatePayload, isChatModel, type ProviderPreset } from '$lib/providers';
  import type { LLMProvider, LLMProviderOAuthStatus } from '$lib/types/api';
  import ProviderPresetIcon from './ProviderPresetIcon.svelte';
  import Button from '$lib/components/ui/Button.svelte';

  let { providers, onChanged }: { providers: LLMProvider[]; onChanged: () => Promise<void> } = $props();
  const presets = [
    { id: 'chatgpt', name: 'Codex', description: 'Use your ChatGPT subscription.' },
    { id: 'openai', name: 'OpenAI', description: 'Connect with an API key.' },
    { id: 'anthropic', name: 'Anthropic', description: 'Connect Claude with an API key.' }
  ] as const;
  let selected = $state<ProviderPreset | null>(null);
  let key = $state('');
  let busy = $state(false);
  let error = $state('');
  let pending = $state<LLMProvider | null>(null);
  let oauth = $state<LLMProviderOAuthStatus | null>(null);
  let codexAuthorized = $state(false);
  const isPrivate = (provider: LLMProvider) => provider.owner_email === auth.getSnapshot().user?.email;
  const configured = (preset: string) => providers.some((provider) => provider.status === 'active' &&
    isPrivate(provider) && provider.config.preset === preset &&
    (preset === 'chatgpt' ? codexAuthorized : provider.last_test?.ok === true) &&
    provider.models.some((model) => isChatModel(model) && model.supports_tools));
  onMount(() => {
    const codex = providers.find((provider) => isPrivate(provider) && provider.config.preset === 'chatgpt' && provider.status === 'active');
    if (codex) void api.llmProviders.chatgptOAuthStatus(codex.provider_id)
      .then((status) => { codexAuthorized = status.status === 'authorized'; }).catch(() => {});
  });

  async function connect() {
    if (!selected) return;
    busy = true; error = '';
    try {
      if (pending && pending.config.preset !== selected) pending = null;
      if (selected === 'chatgpt') {
        pending ??= providers.find((provider) => isPrivate(provider) && provider.config.preset === 'chatgpt') ?? null;
        if (!pending) {
          const form = createProviderForm();
          form.preset = 'chatgpt'; applyProviderPresetDefaults(form);
          form.display_name = 'Codex'; form.owner_scope = 'user'; form.auth_mode = 'oauth';
          pending = await api.llmProviders.create(providerFormToPayload(form));
        }
        oauth = await api.llmProviders.startChatgptOAuth(pending.provider_id);
      } else {
        if (pending?.status === 'active' && !key.trim()) {
          await onChanged(); selected = null; pending = null;
          return;
        }
        const form = createProviderForm();
        form.preset = selected; applyProviderPresetDefaults(form);
        form.display_name = selected === 'openai' ? 'OpenAI' : 'Anthropic';
        form.owner_scope = 'user'; form.auth_mode = 'secret';
        form.auth_secret_name = `${selected}_${crypto.randomUUID().replaceAll('-', '')}`;
        const result = await api.llmProviders.discoverModelsPreview({ preset: selected, base_url: form.base_url, api_key: key.trim() });
        form.models = result.models;
        form.default_model = result.models.find((model) => isChatModel(model) && model.supports_tools)?.model_id ?? '';
        if (!form.default_model) throw new Error('No tool-capable agent models were found for this account.');
        if (pending) {
          const auth = pending.config.auth_config as { secret_name?: string } | undefined;
          if (!auth?.secret_name) throw new Error('This provider needs a credential update in Settings.');
          await api.secrets.upsert({ name: auth.secret_name, value: key.trim(), scope: 'user' });
        } else {
          await api.secrets.upsert({ name: form.auth_secret_name, value: key.trim(), scope: 'user' });
          form.status = 'draft';
          pending = await api.llmProviders.create(providerFormToPayload(form));
        }
        const test = await api.llmProviders.test(pending.provider_id);
        if (!test.ok) throw new Error(test.error_detail || 'Could not connect. Check your API key and account balance.');
        const saved = createProviderForm(pending);
        saved.status = 'active';
        saved.models = form.models; saved.default_model = form.default_model;
        pending = await api.llmProviders.update(pending.provider_id, providerFormToUpdatePayload(saved));
        key = '';
        await onChanged();
        selected = null; pending = null;
      }
    } catch (caught) { error = asApiError(caught).message; }
    finally { busy = false; }
  }
  async function checkSignIn() {
    if (!pending) return;
    busy = true; error = '';
    try {
      oauth = await api.llmProviders.chatgptOAuthStatus(pending.provider_id);
      if (oauth.status === 'authorized' || oauth.status === 'connected') {
        const discovered = await api.llmProviders.discoverModels(pending.provider_id);
        const form = createProviderForm(pending);
        form.models = discovered.models;
        form.default_model = discovered.models.find((model) => isChatModel(model) && model.supports_tools)?.model_id ?? '';
        if (!form.default_model) throw new Error('Sign-in succeeded, but no tool-capable Codex models were found. Retry discovery in Settings.');
        pending = await api.llmProviders.update(pending.provider_id, providerFormToUpdatePayload(form));
        codexAuthorized = true;
        await onChanged();
        selected = null; pending = null; oauth = null;
      }
    } catch (caught) { error = asApiError(caught).message; }
    finally { busy = false; }
  }
</script>

<section class="space-y-4 border-t border-separator pt-5" aria-labelledby="agent-providers-heading">
  <div class="flex items-start gap-3">
    <span aria-hidden="true" class="text-success">✓</span>
    <div>
      <h2 id="agent-providers-heading" class="text-sm font-semibold text-strong">Agent providers <span class="font-normal text-muted">· optional</span></h2>
      <p class="mt-1 text-xs leading-5 text-muted">No extra account required: your agent can use the system provider. Or connect another account below and choose its model when creating the agent.</p>
    </div>
  </div>
  <div class="grid gap-3 sm:grid-cols-3">
    {#each presets as preset}
      <button type="button" disabled={busy} aria-pressed={selected === preset.id} class="rounded-xl border p-3 text-left transition-colors {selected === preset.id ? 'border-accent bg-accent-subtle' : 'border-control-border hover:border-border-strong'}" onclick={() => { selected = selected === preset.id ? null : preset.id; key = ''; error = ''; oauth = null; }}>
        <div class="flex items-center gap-2"><ProviderPresetIcon preset={preset.id} /><strong class="text-sm text-strong">{preset.name}</strong>{#if configured(preset.id)}<span class="ml-auto text-success" aria-label="Configured">✓</span>{/if}</div>
        <p class="mt-3 text-xs leading-5 text-muted">{preset.description}</p>
      </button>
    {/each}
  </div>
  {#if selected}
    <div class="space-y-3 rounded-xl bg-canvas/50 p-4">
      {#if configured(selected)}
        <p class="text-sm text-success">✓ Connected. Available in the agent’s Provider picker.</p>
      {:else if selected === 'chatgpt'}
        <p class="text-sm text-secondary">Sign in with ChatGPT to connect Codex. Your system models stay on the provider above. Agent usage follows your subscription limits.</p>
        {#if oauth?.verification_url && oauth?.user_code}
          <a href={oauth.verification_url} target="_blank" rel="noreferrer" class="text-sm text-accent underline">Open ChatGPT sign-in ↗</a>
          <p class="text-sm text-secondary">Enter this sign-in code: <strong class="font-mono">{oauth.user_code}</strong></p>
          <Button variant="secondary" onclick={checkSignIn} disabled={busy}>Check sign-in</Button>
        {:else}
          <Button variant="secondary" onclick={connect} disabled={busy}>{busy ? 'Connecting…' : 'Sign in with ChatGPT'}</Button>
        {/if}
      {:else}
        <label class="block text-sm text-foreground" for="agent-provider-key">{selected === 'openai' ? 'OpenAI' : 'Anthropic'} API key</label>
        <input id="agent-provider-key" type="password" autocomplete="off" placeholder="Paste your API key" class="w-full rounded-lg border border-control-border bg-canvas p-3 text-sm" bind:value={key} disabled={busy} />
        <p class="text-xs text-muted">Connecting runs a small model test. Your provider charges for API usage.</p>
        <Button variant="secondary" onclick={connect} disabled={busy || (!key.trim() && pending?.status !== 'active')}>{busy ? 'Connecting…' : 'Connect provider'}</Button>
      {/if}
      {#if error}<p role="alert" class="text-sm text-danger">{error}</p>{/if}
    </div>
  {/if}
</section>
