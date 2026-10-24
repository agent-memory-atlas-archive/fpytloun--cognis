<script lang="ts">
  import { onMount } from 'svelte';
  import { beforeNavigate } from '$app/navigation';
  import X from 'lucide-svelte/icons/x';
  import Pencil from 'lucide-svelte/icons/pencil';
  import Copy from 'lucide-svelte/icons/copy';
  import { api, asApiError } from '$lib/api/client';
  import { emptyHook, hookDefinition, hookTriggers, hookTriggerLabels, hookModeLabels, hookModeDescriptions, hookTriggerSummary, type AgentHook, type HookDefinition } from '$lib/hooks';
  import BlockingDialog from '$lib/components/ui/BlockingDialog.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import Badge from '$lib/components/ui/Badge.svelte';
  import { addToast } from '$lib/stores/toasts';
  import { blockNavigationIfDirty, installBeforeUnloadGuard } from '$lib/navigation/unsaved';

  let { hook, readonly = false, onClose, onSaved, onDeleted }: {
    hook: AgentHook | null; readonly?: boolean; onClose: () => void;
    onSaved: (hook: AgentHook) => void; onDeleted: (id: string) => void;
  } = $props();
  let current = $state<AgentHook | null>(null);
  let editing = $state(false);
  let ready = $state(false);
  let busy = $state(false);
  let error = $state('');
  let errorElement = $state<HTMLParagraphElement | null>(null);
  $effect(() => { if (error) errorElement?.focus(); });
  let form = $state<HookDefinition>(emptyHook());
  let args = $state('{}');
  let parameters = $state('{}');
  let snapshot = $state('');
  let confirmation = $state<{ title: string; message: string; accept: string } | null>(null);
  let resolveConfirmation: ((value: boolean) => void) | null = null;
  function confirmLocal(value: { title: string; message: string; accept: string }) {
    confirmation = value;
    return new Promise<boolean>(resolve => { resolveConfirmation = resolve; });
  }
  function finishConfirmation(value: boolean) {
    confirmation = null; resolveConfirmation?.(value); resolveConfirmation = null;
  }
  const dirty = $derived(editing && snapshot !== JSON.stringify({ form, args, parameters }));
  const title = $derived(editing ? (current ? 'Edit hook' : 'New hook') : current?.name ?? 'Hook details');
  const fieldClass = 'mt-1 w-full min-w-0 rounded-lg border border-control-border bg-surface px-3 py-2 text-sm text-foreground placeholder-quiet focus:border-accent focus:outline-none';
  function initialize(source: AgentHook | null) {
    form = source ? hookDefinition(source) : emptyHook();
    args = JSON.stringify(form.tool_call?.args ?? {}, null, 2);
    parameters = JSON.stringify(form.parameters, null, 2);
    snapshot = JSON.stringify({ form, args, parameters });
    error = '';
  }
  onMount(() => {
    current = hook; initialize(hook); editing = !hook && !readonly; ready = true;
    return installBeforeUnloadGuard(() => dirty || busy);
  });
  beforeNavigate(navigation => { blockNavigationIfDirty(navigation, () => dirty || busy); });
  async function canDiscard() {
    return !dirty || await confirmLocal({ title: 'Discard unsaved changes?', message: 'Your hook changes have not been saved.', accept: 'Discard changes' });
  }
  async function close() { if (!busy && await canDiscard()) onClose(); }
  function edit(copy = false) {
    if (readonly || busy || !current || (current.bundled && !copy)) return;
    initialize(current);
    if (copy) { form.name += ' (copy)'; current = null; }
    editing = true;
    snapshot = JSON.stringify({ form, args, parameters });
  }
  async function cancel() {
    if (busy || !await canDiscard()) return;
    if (!current) { onClose(); return; }
    initialize(current); editing = false;
  }
  function objectJSON(value: string, label: string): Record<string, unknown> {
    let parsed: unknown;
    try { parsed = JSON.parse(value); } catch { throw new Error(`${label} must be valid JSON.`); }
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error(`${label} must be a JSON object.`);
    return parsed as Record<string, unknown>;
  }
  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (readonly || busy || current?.bundled) return;
    busy = true; error = '';
    try {
      const payload: HookDefinition = { ...form, name: form.name.trim(), parameters: objectJSON(parameters, 'Parameters') };
      if (payload.action === 'tool_call') {
        if (!payload.tool_call?.tool.trim()) throw new Error('Enter an authorized tool identifier.');
        payload.tool_call = { ...payload.tool_call, tool: payload.tool_call.tool.trim(), args: objectJSON(args, 'Arguments') };
        payload.mode = 'fresh'; payload.prompt = '';
      } else {
        if (!payload.prompt.trim()) throw new Error('Enter instructions for this hook.');
        payload.tool_call = null;
      }
      const saved = current ? await api.hooks.update(current, payload) : await api.hooks.create(payload);
      current = saved; initialize(saved); editing = false; onSaved(saved);
      addToast('Hook saved', 'success');
    } catch (cause) { error = asApiError(cause).message; }
    finally { busy = false; }
  }
  async function remove() {
    if (readonly || busy || !current || current.bundled) return;
    if (!await confirmLocal({ title: 'Delete hook?', message: 'Remove its agent assignments first. Existing run history is preserved.', accept: 'Delete hook' })) return;
    busy = true; error = '';
    try { await api.hooks.remove(current); onDeleted(current.hook_id); addToast('Hook deleted', 'success'); }
    catch (cause) { error = asApiError(cause).message; }
    finally { busy = false; }
  }
  function changeTrigger(value: HookDefinition['trigger']) {
    form.trigger = value;
    const afterTurn = ['conversation_idle', 'turn_completed'].includes(value);
    if (afterTurn && form.mode === 'inject') form.mode = 'fork';
    if (!afterTurn && form.mode === 'follow_up') form.mode = 'inject';
  }
</script>

<BlockingDialog label={title} titleId="hook-detail-title" panelClass="max-w-3xl" dismissible={!busy} backdropDismissible={!dirty}
  onEscape={() => { void close(); return true; }} onClose={() => void close()}>
  {#snippet header()}
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0"><h2 id="hook-detail-title" class="break-words text-base font-semibold text-foreground">{title}</h2>
        <div class="mt-2 flex flex-wrap items-center gap-2">
          <Badge>{current?.bundled ? 'Bundled' : 'Custom'}</Badge>
          {#if current}<span class="text-xs text-quiet">Revision {current.revision}</span>{/if}
        </div>
      </div>
      <Button size="icon" variant="ghost" aria-label="Close hook details" disabled={busy} onclick={() => void close()}><X class="h-5 w-5" /></Button>
    </div>
  {/snippet}

  {#if error}<p bind:this={errorElement} tabindex="-1" role="alert" class="mb-4 rounded-lg border border-danger-border bg-danger-subtle p-3 text-sm text-danger">{error}</p>{/if}
  {#if ready && !editing && current}
    <div class="space-y-6">
      {#if current.description}<p class="text-sm leading-relaxed text-secondary">{current.description}</p>{/if}
      <dl class="grid gap-4 border-y border-separator py-4 sm:grid-cols-2">
        <div><dt class="text-xs text-quiet">When</dt><dd class="mt-1 text-sm text-foreground">{hookTriggerSummary(current)}</dd></div>
        <div><dt class="text-xs text-quiet">Execution</dt><dd class="mt-1 text-sm text-foreground">{hookModeLabels[current.mode]}</dd>
          <p class="mt-1 text-xs leading-relaxed text-muted">{hookModeDescriptions[current.mode]}</p></div>
      </dl>
      <section aria-label="Hook instructions">
        <h3 class="mb-2 text-sm font-medium text-foreground">{current.action === 'prompt' ? 'Instructions' : 'Tool call'}</h3>
        {#if current.action === 'prompt'}
          <p class="whitespace-pre-wrap break-words text-sm leading-relaxed text-secondary">{current.prompt}</p>
        {:else}
          <p class="break-all font-mono text-sm text-foreground">{current.tool_call?.tool}</p>
          <pre class="mt-3 overflow-auto rounded-lg border border-separator bg-surface/60 p-3 text-xs text-secondary">{JSON.stringify(current.tool_call?.args ?? {}, null, 2)}</pre>
          <p class="mt-2 text-xs text-muted">Side effects {current.tool_call?.allow_side_effects ? 'allowed through normal authorization' : 'disabled'}.</p>
        {/if}
      </section>
      {#if current.condition}<section><h3 class="mb-2 text-sm font-medium text-foreground">Run only when</h3>
        <pre class="whitespace-pre-wrap break-words rounded-lg border border-separator bg-surface/60 p-3 text-xs text-secondary">{current.condition}</pre>
      </section>{/if}
      <details class="text-sm">
        <summary class="cursor-pointer text-muted">Parameters and limits</summary>
        <p class="mt-3 text-xs text-muted">Timeout: {current.timeout_seconds} seconds</p>
        <pre class="mt-2 whitespace-pre-wrap break-words font-mono text-xs text-muted">{JSON.stringify(current.parameters, null, 2)}</pre>
      </details>
      <p class="text-xs leading-relaxed text-quiet">
        {current.bundled ? 'Bundled hooks are read-only. Customize a copy to change their behavior.' : 'Changes apply to agents using this hook.'}
        Enable this hook in <a href="/agents" class="text-accent hover:underline">agent settings</a>.
      </p>
    </div>
  {:else if ready && editing}
    <form id="hook-editor-form" onsubmit={save} class="space-y-5">
      <fieldset disabled={busy || readonly} class="space-y-5">
        <label class="block text-sm text-secondary">Name<input class={fieldClass} bind:value={form.name} maxlength="120" required /></label>
        <label class="block text-sm text-secondary">Description<textarea class={fieldClass} bind:value={form.description} rows="2"></textarea></label>
        <div class="grid gap-4 sm:grid-cols-2">
          <label class="block text-sm text-secondary">Trigger<select class={fieldClass} value={form.trigger}
            onchange={event => changeTrigger(event.currentTarget.value as HookDefinition['trigger'])}>
            {#each hookTriggers as trigger}<option value={trigger}>{hookTriggerLabels[trigger]}</option>{/each}
          </select></label>
          <label class="block text-sm text-secondary">Action<select class={fieldClass} bind:value={form.action} onchange={event => {
            if (event.currentTarget.value === 'tool_call') { form.mode = 'fresh'; form.tool_call ??= { tool: '', args: {} }; }
          }}><option value="prompt">Prompt</option><option value="tool_call">Tool call</option></select></label>
        </div>
        {#if form.trigger === 'conversation_idle'}
          <label class="block text-sm text-secondary">Idle time (minutes)<input class={fieldClass} type="number" min="1" max="10080" step="any" value={form.idle_seconds / 60} required
            oninput={event => form.idle_seconds = Math.round(Number(event.currentTarget.value) * 60)} /></label>
        {/if}
        <label class="block text-sm text-secondary">Execution<select class={fieldClass} bind:value={form.mode} aria-describedby="hook-execution-help">
          {#if form.action === 'prompt'}
            {#if !['turn_completed', 'conversation_idle'].includes(form.trigger)}<option value="inject">{hookModeLabels.inject}</option>{/if}
            <option value="fork">{hookModeLabels.fork}</option>
            {#if ['turn_completed', 'conversation_idle'].includes(form.trigger)}<option value="follow_up">{hookModeLabels.follow_up}</option>{/if}
          {/if}
          <option value="fresh">{hookModeLabels.fresh}</option>
        </select></label>
        <p id="hook-execution-help" class="text-xs leading-relaxed text-quiet">{hookModeDescriptions[form.mode]}</p>
        {#if form.action === 'prompt'}
          <label class="block text-sm text-secondary">Instructions<textarea class={`${fieldClass} font-mono`} bind:value={form.prompt} rows="7" required></textarea></label>
        {:else if form.tool_call}
          <label class="block text-sm text-secondary">Tool identifier<input class={fieldClass} bind:value={form.tool_call.tool} required /></label>
          <label class="block text-sm text-secondary">Arguments (JSON)<textarea class={`${fieldClass} font-mono`} bind:value={args} rows="4"></textarea></label>
          <label class="flex items-start gap-2 text-sm text-secondary"><input class="mt-1" type="checkbox" bind:checked={form.tool_call.allow_side_effects} /> Allow side effects through normal authorization</label>
        {/if}
        <details open={Boolean(form.condition)} class="border-t border-separator pt-4">
          <summary class="cursor-pointer text-sm text-secondary">Conditions and advanced settings</summary>
          <div class="mt-4 space-y-4">
            <label class="block text-sm text-secondary">Condition (Jinja boolean)<textarea class={`${fieldClass} font-mono`} value={form.condition ?? ''}
              oninput={event => form.condition = event.currentTarget.value || null} rows="2"></textarea></label>
            <p class="text-xs leading-relaxed text-quiet">Use turn evidence, message text, or cycle counters. <a href="/docs/agent-hooks" target="_blank" rel="noreferrer" class="text-accent hover:underline">Variables and examples ↗</a></p>
            <label class="block text-sm text-secondary">Default parameters (JSON)<textarea class={`${fieldClass} font-mono`} bind:value={parameters} rows="3"></textarea></label>
            <label class="block text-sm text-secondary">Run timeout (seconds)<input class={fieldClass} type="number" min="10" max="3600" bind:value={form.timeout_seconds} required /></label>
          </div>
        </details>
      </fieldset>
    </form>
  {/if}
  {#snippet footer()}
    <div class="flex flex-wrap items-center justify-between gap-3">
      {#if editing}
        <span class="text-xs text-quiet">{dirty ? 'Unsaved changes' : 'Changes affect this definition only until saved.'}</span>
        <div class="flex gap-2"><Button variant="secondary" disabled={busy} onclick={() => void cancel()}>Cancel</Button>
          <Button type="submit" form="hook-editor-form" disabled={busy || readonly}>{busy ? 'Saving…' : 'Save hook'}</Button></div>
      {:else}
        {#if current && !current.bundled && !readonly}<Button variant="ghost" disabled={busy} onclick={remove}>Delete hook</Button>
        {:else}<a class="text-xs text-muted hover:text-foreground" href="/docs/agent-hooks" target="_blank" rel="noreferrer">Hook guide ↗</a>{/if}
        <div class="flex flex-wrap gap-2">
          {#if current && !readonly}
            <Button variant={current.bundled ? 'primary' : 'secondary'} disabled={busy} onclick={() => edit(true)}><Copy class="mr-1 h-4 w-4" />{current.bundled ? 'Customize' : 'Duplicate'}</Button>
            {#if !current.bundled}<Button disabled={busy} onclick={() => edit()}><Pencil class="mr-1 h-4 w-4" /> Edit hook</Button>{/if}
          {/if}
        </div>
      {/if}
    </div>
  {/snippet}
</BlockingDialog>

{#if confirmation}
  <BlockingDialog label={confirmation.title} titleId="hook-confirm-title" onClose={() => finishConfirmation(false)}>
    {#snippet header()}<h2 id="hook-confirm-title" class="font-semibold text-foreground">{confirmation?.title}</h2>{/snippet}
    <p class="text-sm text-secondary">{confirmation.message}</p>
    {#snippet footer()}
      <div class="flex justify-end gap-2">
        <Button variant="secondary" onclick={() => finishConfirmation(false)}>Cancel</Button>
        <Button variant="danger" onclick={() => finishConfirmation(true)}>{confirmation?.accept}</Button>
      </div>
    {/snippet}
  </BlockingDialog>
{/if}
