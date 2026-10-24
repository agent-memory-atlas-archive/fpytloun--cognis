<script lang="ts">
  import { findTarget } from '$lib/find';
  import { onMount } from 'svelte';
  import Search from 'lucide-svelte/icons/search';
  import Plus from 'lucide-svelte/icons/plus';
  import Zap from 'lucide-svelte/icons/zap';
  import RotateCcw from 'lucide-svelte/icons/rotate-ccw';
  import { api, asApiError } from '$lib/api/client';
  import { hookModeLabels, hookTriggerSummary, type AgentHook, type HookRun } from '$lib/hooks';
  import { auth } from '$lib/stores/auth';
  import Button from '$lib/components/ui/Button.svelte';
  import Badge from '$lib/components/ui/Badge.svelte';
  import RegistryCard from '$lib/components/ui/RegistryCard.svelte';
  import HookDetailSheet from './HookDetailSheet.svelte';

  let hooks = $state<AgentHook[]>([]);
  let runs = $state<HookRun[]>([]);
  let loading = $state(true);
  let error = $state('');
  let runError = $state('');
  let runsLoading = $state(false);
  let historyOpen = $state(false);
  let search = $state('');
  let filter = $state('all');
  let selected = $state<AgentHook | null>(null);
  let dialogOpen = $state(false);
  const readonly = $derived($auth.user?.role === 'viewer');
  const filtered = $derived(hooks.filter(hook =>
    (filter === 'all' || (filter === 'bundled') === hook.bundled) &&
    `${hook.name} ${hook.description} ${hookTriggerSummary(hook)} ${hookModeLabels[hook.mode]}`
      .toLowerCase().includes(search.trim().toLowerCase())
  ));
  async function load() {
    loading = true; error = '';
    try { hooks = (await api.hooks.list()).items; }
    catch (cause) { error = asApiError(cause).message; }
    finally { loading = false; }
  }
  async function loadRuns() {
    runsLoading = true; runError = '';
    try { runs = (await api.hooks.runs()).items; }
    catch (cause) { runError = asApiError(cause).message; }
    finally { runsLoading = false; }
  }
  function open(hook: AgentHook | null) { selected = hook; dialogOpen = true; }
  function saved(hook: AgentHook) {
    hooks = [...hooks.filter(item => item.hook_id !== hook.hook_id), hook];
    selected = hook;
  }
  onMount(() => { void load(); });
</script>

<section class="space-y-4" aria-label="Hook registry">
  <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
    <div class="space-y-1">
      <p class="text-sm text-muted">Reusable reminders and background actions, triggered by agent activity.</p>
      <p class="text-xs text-quiet">Enable hooks in <a href="/agents" class="text-accent hover:underline">agent settings</a>.
        <a href="/docs/agent-hooks" class="ml-2 text-accent hover:underline">Hook guide</a></p>
    </div>
    {#if !readonly}<Button size="sm" onclick={() => open(null)}><Plus class="mr-1 h-4 w-4" /> New hook</Button>{/if}
  </div>
  <div class="flex flex-wrap items-center gap-3">
    <div class="relative min-w-0 flex-1 sm:max-w-md">
      <Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-quiet" />
      <input use:findTarget aria-label="Search hooks" placeholder="Search hooks…" bind:value={search}
        class="w-full rounded-lg border border-control-border bg-raised py-2 pl-10 pr-4 text-sm text-foreground placeholder-quiet focus:border-accent focus:outline-none" />
    </div>
    <select aria-label="Hook source" bind:value={filter}
      class="rounded-lg border border-control-border bg-raised px-3 py-2 text-sm text-foreground focus:border-accent focus:outline-none">
      <option value="all">All hooks</option><option value="bundled">Bundled</option><option value="custom">Custom</option>
    </select>
    <span class="text-sm text-quiet">{filtered.length} {filtered.length === 1 ? 'hook' : 'hooks'}</span>
    <Button size="sm" variant="ghost" disabled={loading} onclick={load}><RotateCcw class="mr-1 h-4 w-4" /> Refresh</Button>
  </div>
  {#if error}<div role="alert" class="rounded-lg border border-danger-border bg-danger-subtle p-3 text-sm text-danger">
    Could not load hooks. {error} <button class="underline" onclick={load}>Retry</button>
  </div>{/if}
  {#if loading && !hooks.length}<p role="status" class="py-12 text-center text-sm text-muted">Loading hooks…</p>
  {:else if !filtered.length && !error}
    <div class="py-12 text-center text-quiet">
      <Zap class="mx-auto mb-2 h-8 w-8 opacity-50" />
      <p>{search || filter !== 'all' ? 'No hooks match these filters.' : 'No hooks yet.'}</p>
      <p class="mt-1 text-sm">{search || filter !== 'all' ? 'Try another search or source.' : 'Create a hook to automate agent follow-ups.'}</p>
    </div>
  {:else}
    <div class="space-y-2">
      {#each filtered as hook (hook.hook_id)}
        <RegistryCard label={hook.name} onclick={() => open(hook)}>
          <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <Zap class="h-4 w-4 shrink-0 text-muted" />
                <span class="break-words font-medium text-foreground">{hook.name}</span>
                <Badge class={hook.bundled ? 'border-accent/30 bg-accent-subtle text-accent' : ''}>{hook.bundled ? 'Bundled' : 'Custom'}</Badge>
              </div>
              <p class="mt-1 break-words text-sm text-muted">{hook.description || 'No description.'}</p>
            </div>
            <span class="shrink-0 text-xs text-quiet">Open details</span>
          </div>
          <div class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-quiet">
            <span>When: <span class="text-muted">{hookTriggerSummary(hook)}</span></span>
            <span>Runs as: <span class="text-muted">{hookModeLabels[hook.mode]}</span></span>
            {#if hook.action === 'tool_call'}<span>Action: <span class="text-muted">Tool call</span></span>{/if}
            {#if hook.condition}<span class="text-muted">Conditional</span>{/if}
          </div>
        </RegistryCard>
      {/each}
    </div>
  {/if}
  <section class="border-t border-separator pt-4" aria-label="Hook runs">
    <button class="flex min-h-10 items-center gap-2 text-sm text-muted hover:text-foreground"
      aria-expanded={historyOpen} onclick={() => { historyOpen = !historyOpen; if (historyOpen) void loadRuns(); }}>
      <span aria-hidden="true">{historyOpen ? '▾' : '▸'}</span> Recent runs
    </button>
    {#if historyOpen}
      {#if runsLoading}<p class="py-3 text-sm text-quiet" role="status">Loading runs…</p>
      {:else if runError}<p role="alert" class="py-3 text-sm text-danger">{runError} <button class="underline" onclick={loadRuns}>Retry</button></p>
      {:else if !runs.length}<p class="py-3 text-sm text-quiet">No runs yet. Enable a hook for an agent to get started.</p>
      {:else}<ul class="divide-y divide-separator">
        {#each runs as run (run.run_id)}
          <li class="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
            <div class="min-w-0"><p class="break-words text-foreground">{hooks.find(hook => hook.hook_id === run.hook_id)?.name ?? run.hook_id}</p>
              <p class="text-xs text-quiet">{new Date(run.created_at).toLocaleString()} · {run.status.replaceAll('_', ' ')}</p></div>
            <a class="shrink-0 text-accent hover:underline" href={`/chat/${encodeURIComponent(run.conversation_id)}`}>Source conversation</a>
          </li>
        {/each}
      </ul>{/if}
    {/if}
  </section>
</section>

{#if dialogOpen}
  <HookDetailSheet hook={selected} {readonly} onClose={() => dialogOpen = false} onSaved={saved}
    onDeleted={id => { hooks = hooks.filter(hook => hook.hook_id !== id); dialogOpen = false; }} />
{/if}
