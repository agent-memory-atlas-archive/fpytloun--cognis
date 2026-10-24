<script lang="ts">
  import { onMount } from 'svelte';
  import { api, asApiError } from '$lib/api/client';
  import type { AgentHook, HookAssignment } from '$lib/hooks';
  import Button from '$lib/components/ui/Button.svelte';
  import { auth } from '$lib/stores/auth';
  import { addToast } from '$lib/stores/toasts';

  let { agentId } = $props<{ agentId: string }>();
  let hooks = $state<AgentHook[]>([]);
  let assignments = $state<HookAssignment[]>([]);
  let loading = $state(true);
  let busy = $state(false);
  let error = $state('');
  let selected = $state('');
  let editing = $state<string | null>(null);
  let parameters = $state('{}');
  const readonly = $derived($auth.user?.role === 'viewer');
  const available = $derived(hooks.filter(hook => !assignments.some(a => a.hook_id === hook.hook_id)));
  const selectedHook = $derived(available.find(hook => hook.hook_id === selected));
  async function load() {
    loading = true;
    try {
      const [registry, current] = await Promise.all([api.hooks.list(), api.hooks.assignments(agentId)]);
      hooks = registry.items; assignments = current.items; error = '';
    } catch (cause) { error = asApiError(cause).message; }
    finally { loading = false; }
  }
  async function save(assignment: HookAssignment, message?: string) {
    if (busy || readonly) return;
    busy = true; error = '';
    try {
      const result = await api.hooks.assign(agentId, assignment);
      assignments = [...assignments.filter(a => a.hook_id !== result.hook_id), result];
      editing = null; selected = '';
      addToast(message ?? (result.enabled ? 'Hook enabled.' : 'Hook disabled.'), 'success');
    } catch (cause) { error = asApiError(cause).message; }
    finally { busy = false; }
  }
  async function saveParameters(assignment: HookAssignment) {
    try {
      const parsed = JSON.parse(parameters);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('Parameters must be a JSON object.');
      await save({ ...assignment, parameters: parsed }, 'Hook parameters saved.');
    } catch (cause) { error = cause instanceof Error ? cause.message : String(cause); }
  }
  async function remove(hookId: string) {
    if (busy || readonly) return;
    busy = true; error = '';
    try {
      await api.hooks.unassign(agentId, hookId);
      assignments = assignments.filter(a => a.hook_id !== hookId);
      addToast('Hook removed.', 'success');
    } catch (cause) { error = asApiError(cause).message; }
    finally { busy = false; }
  }
  onMount(load);
</script>

<section class="rounded-2xl border border-separator p-4 text-foreground sm:p-5" aria-label="Agent hooks">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <h2 class="text-lg font-semibold">Hooks</h2>
    <a class="text-sm text-accent hover:text-accent-hover underline" href="/tools?tab=hooks">Manage hook definitions</a>
  </div>
  <p class="mt-1 text-sm text-muted">Enable reusable reminders and background actions for this agent.</p>
  {#if error}<p role="alert" class="mt-3 text-danger">{error} <button class="underline" onclick={load}>Retry loading</button></p>{/if}
  {#if loading}<p class="mt-3 text-sm text-muted">Loading hooks…</p>
  {:else}
    <ul class="mt-3 divide-y divide-separator">
      {#each assignments as assignment (assignment.hook_id)}
        {@const hook = hooks.find(h => h.hook_id === assignment.hook_id)}
        <li class="py-3">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div><strong>{hook?.name ?? assignment.hook_id}</strong><p class="text-sm text-muted">{hook?.description}</p></div>
            <div class="flex flex-wrap items-center gap-3">
              <label class="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={assignment.enabled} disabled={readonly || busy}
                  onchange={(event) => {
                    const enabled = event.currentTarget.checked;
                    event.currentTarget.checked = assignment.enabled;
                    void save({ ...assignment, enabled });
                  }} /> Enabled
              </label>
              <Button variant="secondary" size="sm" disabled={readonly || busy} onclick={() => {
                editing = assignment.hook_id; parameters = JSON.stringify(assignment.parameters, null, 2);
              }}>Parameters</Button>
              <Button variant="ghost" size="sm" disabled={readonly || busy} onclick={() => remove(assignment.hook_id)}>Remove</Button>
            </div>
          </div>
          {#if editing === assignment.hook_id}
            <label class="mt-3 block text-sm">Parameter overrides (JSON object)
              <textarea class="mt-1 w-full rounded-lg border border-control-border bg-inset p-2 font-mono text-foreground focus:border-accent" rows="4" bind:value={parameters}></textarea>
            </label>
            <div class="mt-2 flex gap-2">
              <Button size="sm" disabled={busy} onclick={() => saveParameters(assignment)}>Save parameters</Button>
              <Button size="sm" variant="ghost" onclick={() => editing = null}>Cancel</Button>
            </div>
          {/if}
        </li>
      {/each}
    </ul>
    {#if assignments.length === 0}<p class="my-3 text-sm text-muted">No hooks assigned. Choose a bundled hook or create your own.</p>{/if}
    {#if !readonly}
      <div class="mt-3 flex flex-wrap gap-2">
        <label class="min-w-0 flex-1"><span class="sr-only">Hook to assign</span>
          <select class="w-full rounded-xl border border-control-border bg-surface p-2 text-sm text-foreground focus:border-accent" bind:value={selected}>
            <option value="">Choose a hook</option>
            {#each available as hook}<option value={hook.hook_id}>{hook.name}{hook.bundled ? ' · bundled' : ''}</option>{/each}
          </select>
        </label>
        <Button disabled={!selected || busy} onclick={() => save({ hook_id: selected, enabled: true, parameters: {} })}>Enable hook</Button>
      </div>
      {#if selectedHook}<p class="mt-2 text-sm text-muted">{selectedHook.description}</p>{/if}
    {/if}
  {/if}
</section>
