<script lang="ts">
  import { onMount } from 'svelte';
  import { api, asApiError } from '$lib/api/client';
  import { executorInstallCommands, executorReady } from '$lib/onboarding';
  import Button from '$lib/components/ui/Button.svelte';
  import type { ExecutorConfig } from '$lib/types/api';
  let { onChanged, onContinue, initialExecutorId = '' }: { onChanged: () => Promise<void>; onContinue: (id: string) => void; initialExecutorId?: string } = $props();
  let executors = $state<ExecutorConfig[]>([]);
  let selectedId = $state('');
  let name = $state('My computer');
  let platform = $state('macos');
  let origin = $state('');
  let token = $state('');
  let busy = $state(false);
  let polling = false;
  let error = $state('');
  let notice = $state('');
  let advanced = $state(false);
  const selected = $derived(executors.find((executor) => executor.executor_id === selectedId));
  const ready = $derived(!!selected && executorReady(selected));
  const commands = $derived.by(() => {
    if (!origin) return '';
    try { return executorInstallCommands(platform, origin); } catch { return ''; }
  });
  async function load() {
    executors = await api.executor.list();
    selectedId ||= executors.find(executorReady)?.executor_id ?? executors[0]?.executor_id ?? '';
  }
  async function prepare() {
    busy = true; error = ''; notice = '';
    try {
      if (!selectedId) {
        const executor = await api.executor.create({
          name, executor_type: 'websocket', shared: false,
          enabled_tool_groups: ['filesystem', 'shell', 'browser'],
        });
        selectedId = executor.executor_id;
        await load();
      }
      token = (await api.executor.generateToken(selectedId)).token;
    } catch (caught) { error = asApiError(caught).message; }
    finally { busy = false; }
  }
  async function refresh() {
    if (polling || busy) return;
    polling = true;
    try { await load(); }
    catch (caught) { error = asApiError(caught).message; }
    finally { polling = false; }
  }
  async function next() {
    busy = true; error = '';
    try {
      await load();
      const current = executors.find((executor) => executor.executor_id === selectedId);
      if (!current || !executorReady(current)) throw new Error('Your computer is not connected yet. Run the installation command, then try again.');
      await onChanged();
      onContinue(selectedId);
    } catch (caught) { error = asApiError(caught).message; }
    finally { busy = false; }
  }
  async function copy(value: string, label: string) {
    try { await navigator.clipboard.writeText(value); notice = `${label} copied.`; }
    catch { error = 'Clipboard unavailable. Select and copy the text manually.'; }
  }
  onMount(() => {
    origin = window.location.origin;
    selectedId = initialExecutorId;
    platform = /Mac|iPhone|iPad/i.test(navigator.platform) ? 'macos' : 'docker';
    void load().catch((caught) => { error = asApiError(caught).message; });
    const timer = setInterval(() => {
      if (selectedId && !ready && !document.hidden) void refresh();
    }, 3000);
    return () => { clearInterval(timer); token = ''; };
  });
</script>

<div class="space-y-6">
  <div>
    <h1 class="text-2xl font-semibold text-strong">Setup executor</h1>
    <p class="mt-3 text-sm leading-6 text-muted">Connect a computer where your assistant can run tools and work with files.</p>
  </div>
  {#if ready}
    <div class="rounded-lg bg-success-subtle p-4 text-sm text-success" role="status">✓ {selected?.name} is connected.</div>
    <Button onclick={next} disabled={busy}>Continue</Button>
  {:else}
    <div class="flex flex-wrap gap-2" aria-label="Executor platform">
      {#each [{ id: 'macos', label: 'macOS' }, { id: 'docker', label: 'Docker' }, { id: 'kubernetes', label: 'Kubernetes' }] as option}
        <button type="button" aria-pressed={platform === option.id} class={`rounded-lg border px-4 py-2 text-sm ${platform === option.id ? 'border-accent bg-accent-subtle text-accent' : 'border-control-border text-muted'}`} onclick={() => { platform = option.id; }}>{option.label}</button>
      {/each}
    </div>
    <p class="text-sm text-muted">{platform === 'macos' ? 'Install on your Mac with Homebrew. Run without sudo.' : platform === 'docker' ? 'Install in Docker. The assistant can access its container and mounted workspace.' : 'Install in your Kubernetes cluster. Requires kubectl and persistent storage.'}</p>
    {#if !token}
      <p class="text-xs text-muted">This grants filesystem, shell, and browser access on the selected computer. Keep your connection code private.</p>
      {#if selected}<p class="text-xs text-warning">This replaces the connection code for {selected.name}. Its previous code will stop working.</p>{/if}
      <Button onclick={prepare} disabled={busy}>{busy ? 'Preparing…' : 'Get setup command'}</Button>
    {:else}
      <div class="space-y-3">
        <p class="text-sm text-foreground">1. Paste this into {platform === 'kubernetes' ? 'a terminal with cluster access' : 'your terminal'}.</p>
        {#if commands}
          <pre class="max-h-52 overflow-auto rounded-lg bg-canvas p-4 text-xs leading-6 text-secondary">{commands}</pre>
          <Button variant="secondary" onclick={() => copy(commands, 'Command')}>Copy command</Button>
        {:else}
          <p role="alert" class="text-sm text-warning">Set a reachable HTTPS controller URL in Advanced options.</p>
        {/if}
        <p class="pt-2 text-sm text-foreground">2. When asked, paste your connection code.</p>
        <div class="flex gap-3">
          <input type="password" aria-label="Private connection code" value={token} readonly class="min-w-0 flex-1 rounded-lg border border-control-border bg-canvas px-3 py-2 text-sm" />
          <Button variant="secondary" onclick={() => copy(token, 'Connection code')}>Copy code</Button>
        </div>
        <p class="pt-3 text-sm text-muted" role="status">Waiting for your computer to connect… This updates automatically.</p>
      </div>
    {/if}
  {/if}
  {#if error}<p role="alert" class="text-sm text-danger">{error}</p>{/if}
  {#if notice}<p role="status" class="text-xs text-accent">{notice}</p>{/if}
  <details bind:open={advanced} class="border-t border-separator pt-4">
    <summary class="cursor-pointer text-sm text-muted">Advanced options</summary>
    <div class="mt-4 space-y-4">
      <label class="block text-sm">Existing executor
        <select class="mt-2 w-full rounded-lg bg-canvas p-2" bind:value={selectedId} onchange={() => { token = ''; }}>
          <option value="">Create a new executor</option>
          {#each executors as executor}<option value={executor.executor_id}>{executor.name} — {executor.runtime_state}</option>{/each}
        </select>
      </label>
      <label class="block text-sm">Computer name<input class="mt-2 w-full rounded-lg bg-canvas p-2" bind:value={name} /></label>
      <label class="block text-sm">Controller URL<input class="mt-2 w-full rounded-lg bg-canvas p-2" bind:value={origin} /></label>
      <p class="text-xs leading-5 text-muted">Use HTTPS outside local development. Local HTTP Docker commands use Linux host networking; Docker Desktop needs host networking enabled. Homebrew must already be installed on macOS. Kubernetes needs a trusted HTTPS URL, a default StorageClass, and a fresh cognis-executor namespace.</p>
      <p class="text-xs text-warning">Generating a new connection code revokes the previous one for this executor.</p>
      {#if selected && !ready}<Button variant="secondary" onclick={prepare} disabled={busy}>Replace connection code</Button>{/if}
      <Button variant="secondary" onclick={refresh} disabled={busy}>Check connection</Button>
      <a href="/docs/executors" class="block text-sm text-accent">Installation help and troubleshooting →</a>
    </div>
  </details>
</div>
