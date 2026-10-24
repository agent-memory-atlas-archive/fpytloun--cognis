<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { api } from '$lib/api/client';
  import { auth } from '$lib/stores/auth';
  import KnowledgeCard from '$lib/components/knowledge/KnowledgeCard.svelte';
  import KnowledgeWorkspace from '$lib/components/knowledge/KnowledgeWorkspace.svelte';
  import DashboardModalShell from '$lib/components/dashboard/DashboardModalShell.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import type { KnowledgebaseModel } from '$lib/types/api';

  let { projectId, canManage } = $props<{ projectId: string; canManage: boolean }>();
  let assigned = $state<KnowledgebaseModel[]>([]);
  let available = $state<KnowledgebaseModel[]>([]);
  let selected = $state('');
  let opened = $state<string | null>(null);
  let loading = $state(true);
  let busy = $state(false);
  let error = $state('');
  let alive = true;
  onDestroy(() => { alive = false; });
  const editable = $derived(canManage && $auth.user?.role !== 'viewer');
  const removable = (kb: KnowledgebaseModel) => Boolean($auth.user) &&
    $auth.user?.role !== 'viewer' && (editable || kb.owner_email === $auth.user?.email);
  const options = $derived(available.filter((kb) => kb.access_level === 'owner' &&
    kb.status === 'active' && !assigned.some((item) => item.knowledgebase_id === kb.knowledgebase_id)));

  async function load() {
    error = '';
    try {
      const [items, all] = await Promise.all([
        api.projects.knowledgebases(projectId),
        editable ? api.knowledgebases.list() : Promise.resolve([]),
      ]);
      if (alive) { assigned = items; available = all; }
    } catch (caught) { if (alive) error = String(caught); }
    finally { if (alive) loading = false; }
  }
  async function change(id: string, attach: boolean) {
    const item = assigned.find((kb) => kb.knowledgebase_id === id);
    if (busy || !id || (attach ? !editable : !item || !removable(item))) return;
    busy = true;
    try {
      await api.projects.assignKnowledgebase(projectId, id, attach);
      if (!alive) return;
      selected = '';
      await load();
    } catch (caught) { if (alive) error = String(caught); }
    finally { if (alive) busy = false; }
  }
  onMount(() => { void load(); });
</script>

<section class="min-w-0 space-y-4" aria-label="Project knowledgebases">
  <div>
    <h2 class="text-lg font-semibold text-strong">Knowledgebases</h2>
    <p class="text-sm text-muted">Project members can browse and query shared knowledge. Editing remains with the knowledgebase owner.</p>
  </div>
  {#if editable}
    <div class="flex min-w-0 flex-wrap gap-2">
      <select aria-label="Knowledgebase to share" bind:value={selected} class="min-w-0 max-w-full rounded-xl border border-control-border bg-canvas p-2 text-sm">
        <option value="">Select an owned knowledgebase</option>
        {#each options as kb}<option value={kb.knowledgebase_id}>{kb.name}</option>{/each}
      </select>
      <Button disabled={!selected || busy} onclick={() => void change(selected, true)}>Share with project</Button>
    </div>
  {/if}
  {#if error}<p role="alert" class="text-danger">{error}</p><Button onclick={() => void load()}>Retry</Button>{/if}
  {#if loading}<p>Loading knowledgebases…</p>{/if}
  <div class="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2">
    {#each assigned as kb (kb.knowledgebase_id)}
      <div class="min-w-0 space-y-2">
        <KnowledgeCard {kb} canMutate={false} onOpen={() => { opened = kb.knowledgebase_id; }} />
        {#if removable(kb)}<Button variant="ghost" disabled={busy} onclick={() => void change(kb.knowledgebase_id, false)}>Remove from project</Button>{/if}
      </div>
    {:else}
      {#if !loading && !error}<p class="text-muted">No knowledgebases shared with this project.</p>{/if}
    {/each}
  </div>
</section>

{#if opened}
  <DashboardModalShell title="Knowledgebase" testId="project-knowledge-modal" onClose={() => { opened = null; void load(); }}>
    <div class="min-h-0 min-w-0 flex-1 overflow-auto">
      {#key opened}<KnowledgeWorkspace kbId={opened} embedded onClose={() => { opened = null; void load(); }} />{/key}
    </div>
  </DashboardModalShell>
{/if}
