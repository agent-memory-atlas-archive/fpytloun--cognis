<script lang="ts">
  import { api } from '$lib/api/client';
  import BlockingDialog from '$lib/components/ui/BlockingDialog.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import AgentAvatar from '$lib/components/AgentAvatar.svelte';
  import AgentAccessPicker from './AgentAccessPicker.svelte';
  import Plus from 'lucide-svelte/icons/plus';
  import X from 'lucide-svelte/icons/x';
  import { auth } from '$lib/stores/auth';
  import TextDocument from '$lib/components/TextDocument.svelte';
  import { syntaxError, textFormat } from '$lib/artifact-text';
  import type { AgentAccess, ResourceChange } from '$lib/artifact-authoring';
  import Eye from 'lucide-svelte/icons/eye';
  import { beforeNavigate } from '$app/navigation';
  let { projectId, onClose, onCreated }: { projectId?: string; onClose: () => void; onCreated: ResourceChange } = $props();
  let method = $state('text');
  let filename = $state('');
  let mime = $state('text/plain');
  let text = $state('');
  let file = $state<File | null>(null);
  let preview = $state(false);
  let agents = $state<AgentAccess[]>([]);
  let selected = $state<string[]>([]);
  let error = $state('');
  let busy = $state(false);
  let selectingAgents = $state(false);
  let draftAgents = $state<string[]>([]);
  const invalid = $derived(method === 'text' ? syntaxError(text, mime, filename) : '');
  const dirty = $derived(!!(filename || text || file));
  let submitted = $state(false);
  beforeNavigate((navigation) => {
    if (!submitted && (busy || (dirty && !confirm('Discard this new artifact?')))) navigation.cancel();
  });
  $effect(() => {
    let cancelled = false;
    void api.artifactDocuments.agents().then((value) => { if (!cancelled) agents = value; })
      .catch((caught) => { if (!cancelled) error = caught instanceof Error ? caught.message : 'Agent selection unavailable.'; });
    return () => { cancelled = true; };
  });
  function close() { if (!busy && (!dirty || confirm('Discard this new artifact?'))) onClose(); }
  async function save() {
    busy = true; error = '';
    try {
      const created = method === 'file' && file
        ? await api.artifactDocuments.upload(file, filename, selected, projectId)
        : await api.artifactDocuments.create({ filename, content: text, mime_type: mime, agent_ids: selected, project_id: projectId });
      submitted = true;
      onCreated(created);
    } catch (caught) { error = caught instanceof Error ? caught.message : 'Could not create artifact. Your input is preserved.'; }
    finally { busy = false; }
  }
</script>

<svelte:window onbeforeunload={(event) => { if (!submitted && (dirty || busy)) { event.preventDefault(); event.returnValue = ''; } }} />
<BlockingDialog label="New artifact" onClose={close} panelClass="max-w-3xl" bodyClass="space-y-5" dismissible={!busy} backdropDismissible={!dirty}>
  {#snippet header()}
    <div class="flex items-center justify-between"><h2 class="text-lg font-semibold text-foreground">New artifact</h2><Button variant="ghost" size="icon" aria-label="Close new artifact" onclick={close} disabled={busy}><X size={18} /></Button></div>
  {/snippet}
  <div class="space-y-5" data-testid="new-artifact-modal">
    <div class="inline-flex gap-1 rounded-xl bg-surface p-1" role="tablist" aria-label="Creation method">
      <button role="tab" aria-selected={method === 'text'} class={`min-h-10 rounded-lg px-4 text-sm transition ${method === 'text' ? 'bg-inset text-strong shadow-sm' : 'text-muted hover:bg-raised hover:text-strong'}`} onclick={() => { method = 'text'; preview = false; }}>Write text</button>
      <button role="tab" aria-selected={method === 'file'} class={`min-h-10 rounded-lg px-4 text-sm transition ${method === 'file' ? 'bg-inset text-strong shadow-sm' : 'text-muted hover:bg-raised hover:text-strong'}`} onclick={() => { method = 'file'; preview = false; }}>Upload file</button>
    </div>
    {#if method === 'file'}
      <label class="block text-sm text-secondary">File (up to 20 MB)<input aria-label="Upload file" type="file" class="mt-2 block min-h-11 w-full" onchange={(event) => { file = event.currentTarget.files?.[0] ?? null; if (file) filename = file.name; }} /></label>
    {/if}
    <label class="block text-sm text-secondary">File name<input aria-label="Artifact name" bind:value={filename} maxlength="240" placeholder="notes.md" class="mt-2 min-h-11 w-full rounded-lg border border-control-border bg-canvas px-3" /></label>
    {#if method === 'text'}
      <div class="flex flex-wrap items-center justify-between gap-3">
        <label class="text-sm text-secondary">Format<select aria-label="Artifact format" bind:value={mime} class="ml-2 min-h-11 rounded-lg border border-control-border bg-canvas px-3">
          <option value="text/plain">Plain text</option><option value="application/json">JSON</option><option value="text/markdown">Markdown</option><option value="text/html">HTML</option><option value="application/yaml">YAML</option><option value="text/csv">CSV</option>
        </select></label>
        <button aria-pressed={preview} class="inline-flex min-h-11 items-center gap-2 px-3 text-accent" onclick={() => { preview = !preview; }}><Eye size={16} />{preview ? 'Source' : 'Preview'}</button>
      </div>
      <div class="rounded-lg border border-control-border"><TextDocument bind:text {mime} {filename} editing {preview} label="New artifact content" /></div>
      {#if invalid}<p role="alert" class="text-sm text-warning">{invalid}</p>{/if}
    {/if}
    <section class="space-y-3 border-t border-separator pt-4" aria-label="Agent access">
      <h3 class="text-xs font-medium text-muted">Owner &amp; agent access</h3>
      <div class="flex flex-wrap items-center gap-2">
        <span title={`${$auth.user?.name || 'You'} · Owner`}><AgentAvatar name={$auth.user?.name || 'You'} class="!h-9 !w-9" /></span>
        {#each agents.filter(a => selected.includes(a.agent_id)) as agent (agent.agent_id)}
          <span title={agent.name}><AgentAvatar name={agent.name} avatarUrl={agent.avatar_url} class="!h-9 !w-9" /></span>
        {/each}
        <Button variant="secondary" size="icon-mobile" aria-label="Select agents" onclick={() => { draftAgents = [...selected]; selectingAgents = true; }}><Plus size={17} /></Button>
      </div>
      <p class="text-xs text-quiet">{projectId ? 'Shared with this project. Add agents for explicit access.' : 'Private to you unless you add agents.'}</p>
    </section>
    {#if error}<p role="alert" class="text-sm text-danger">{error}</p>{/if}
  </div>
  {#snippet footer()}
    <div class="flex justify-end gap-2">
      <Button variant="ghost" disabled={busy} onclick={close}>Cancel</Button>
      <Button disabled={busy || !filename.trim() || !!invalid || (method === 'file' && (!file || file.size > 20 * 1024 * 1024))} onclick={save}>{busy ? 'Creating…' : 'Create artifact'}</Button>
    </div>
  {/snippet}
</BlockingDialog>
{#if selectingAgents}
  <BlockingDialog label="Share with agents" onClose={() => { selectingAgents = false; }} backdropDismissible={[...draftAgents].sort().join('\0') === [...selected].sort().join('\0')} panelClass="max-w-xl" bodyClass="space-y-4">
    {#snippet header()}<div class="flex items-center justify-between"><h2 class="text-lg font-semibold text-strong">Share with agents</h2><Button variant="ghost" size="icon" aria-label="Close agent selection" onclick={() => { selectingAgents = false; }}><X size={18} /></Button></div>{/snippet}
    <p class="text-sm text-muted">Choose agents who can access this artifact after you create it.</p>
    <AgentAccessPicker {agents} bind:selected={draftAgents} />
    {#snippet footer()}<div class="flex justify-end gap-2"><Button variant="ghost" onclick={() => { selectingAgents = false; }}>Cancel</Button><Button onclick={() => { selected = [...draftAgents]; selectingAgents = false; }}>Done</Button></div>{/snippet}
  </BlockingDialog>
{/if}
