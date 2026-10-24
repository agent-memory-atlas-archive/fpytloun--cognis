<script lang="ts">
  import { findTarget } from '$lib/find';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { onDestroy } from 'svelte';
  import { auth } from '$lib/stores/auth';
  import { preferenceKey, preferenceKeys, readPreferences, savePreferences } from '$lib/library-preferences';
  import { api } from '$lib/api/client';
  import Search from 'lucide-svelte/icons/search';
  import List from 'lucide-svelte/icons/list';
  import FolderTree from 'lucide-svelte/icons/folder-tree';
  import ResourceBranch from './ResourceBranch.svelte';
  import ResourceModal from './ResourceModal.svelte';
  import NewArtifactModal from './NewArtifactModal.svelte';
  import Plus from 'lucide-svelte/icons/plus';
  import Star from 'lucide-svelte/icons/star';
  import { favoriteRevision } from '$lib/document-favorites';
  import { formatLabel, type LibraryFilters, type LibraryGrouping, type LibraryGroup, type LibraryItem } from '$lib/library';

  let { projectId }: { projectId?: string } = $props();
  const selectedRef = $derived(page.url.searchParams.get('lib_item') ?? '');
  const selectedKind = $derived(page.url.searchParams.get('lib_item_kind') === 'artifact' ? 'artifact' : 'deliverable');
  let readyScope = $state('');
  let creating = $state(false);
  let revision = $state(0);
  function changed(item: LibraryItem) {
    revision++;
    const url = new URL(page.url);
    url.searchParams.set('lib_item', item.id);
    url.searchParams.set('lib_item_kind', item.kind);
    void goto(url, { replaceState: true, noScroll: true, keepFocus: true });
  }
  const scope = $derived($auth.user?.email ? preferenceKey($auth.user.email, projectId) : '');
  $effect(() => {
    const current = scope;
    if (!current || readyScope === current) return;
    const url = new URL(page.url);
    const explicit = preferenceKeys.some((name) => url.searchParams.has(`lib_${name}`));
    let stored: URLSearchParams;
    try { stored = readPreferences(localStorage, current); } catch { stored = new URLSearchParams(); }
    if (!explicit && stored.size) {
      for (const [key, value] of stored) url.searchParams.set(key, value);
      void goto(url, { replaceState: true, noScroll: true, keepFocus: true }).then(() => { readyScope = current; });
    } else readyScope = current;
  });
  $effect(() => {
    if (!scope || readyScope !== scope) return;
    const params = page.url.searchParams;
    try { savePreferences(localStorage, scope, params); } catch { /* Storage may be unavailable. */ }
  });
  const param = (name: string) => page.url.searchParams.get(`lib_${name}`) ?? '';
  const kind = $derived(param('kind') === 'artifact' ? 'artifact' : 'deliverable');
  const grouping = $derived((['project', 'conversation', 'project_conversation'].includes(param('group')) ? param('group') : 'none') as LibraryGrouping);
  const levels = $derived(grouping === 'project_conversation' ? ['project', 'conversation'] as const : grouping === 'none' ? [] : [grouping] as ('project' | 'conversation')[]);
  // Modal query parameters must not invalidate loaded list pages or folders.
  const filterKey = $derived(JSON.stringify({
    kind, q: param('q'),
    favorites: param('favorites') === 'true',
    project_id: projectId ?? (param('project') || undefined),
    agent_id: param('agent') || undefined,
    origin: kind === 'artifact' && ['user', 'agent', 'other'].includes(param('origin')) ? param('origin') as LibraryFilters['origin'] : 'all',
    ownership: ['mine', 'shared'].includes(param('ownership')) ? param('ownership') as LibraryFilters['ownership'] : 'all',
    format: param('format') || undefined,
    after: param('after') ? `${param('after')}T00:00:00Z` : undefined,
    before: param('before') ? `${param('before')}T23:59:59.999Z` : undefined,
    sort: param('sort') === 'created' ? 'created' : 'updated',
  }));
  const filters: LibraryFilters = $derived(JSON.parse(filterKey));
  let search = $state('');
  let timer: ReturnType<typeof setTimeout>;
  let showFilters = $state(false);
  let projects = $state<LibraryGroup[]>([]);
  let agents = $state<LibraryGroup[]>([]);
  let formats = $state<LibraryGroup[]>([]);
  let facetError = $state('');
  const activeFilterCount = $derived(['project', 'agent', 'origin', 'ownership', 'format', 'after', 'before'].filter((key) => param(key)).length);

  $effect(() => { search = param('q'); });
  async function change(name: string, value: string) {
    clearTimeout(timer);
    const url = new URL(page.url);
    url.searchParams.set('lib_view', '1');
    if (value) url.searchParams.set(`lib_${name}`, value); else url.searchParams.delete(`lib_${name}`);
    if (name === 'kind') {
      url.searchParams.delete('lib_format');
      url.searchParams.delete('lib_origin');
    }
    await goto(url, { keepFocus: true, noScroll: true, replaceState: name === 'q' });
  }
  function searchChanged(value: string) {
    search = value;
    clearTimeout(timer);
    timer = setTimeout(() => void change('q', value.trim()), 250);
  }
  async function clearFilters() {
    clearTimeout(timer);
    const url = new URL(page.url);
    for (const key of [...url.searchParams.keys()]) {
      if (key.startsWith('lib_') && !['lib_kind', 'lib_group'].includes(key)) url.searchParams.delete(key);
    }
    url.searchParams.set('lib_view', '1');
    await goto(url, { keepFocus: true, noScroll: true });
  }
  function openResource(item: LibraryItem) {
    const url = new URL(page.url);
    url.searchParams.set('lib_item', item.id);
    url.searchParams.set('lib_item_kind', item.kind);
    void goto(url, { noScroll: true, keepFocus: true });
  }
  function closeResource() {
    const url = new URL(page.url);
    url.searchParams.delete('lib_item');
    url.searchParams.delete('lib_item_kind');
    void goto(url, { noScroll: true, keepFocus: true, replaceState: true });
  }
  $effect(() => {
    const base: LibraryFilters = { kind, project_id: projectId };
    let cancelled = false;
    facetError = '';
    async function collect(by: 'project' | 'agent' | 'format') {
      const result: LibraryGroup[] = [];
      let cursor: string | undefined;
      do {
        const next = await api.library.groups(base, by, cursor);
        if (cancelled) return [];
        result.push(...next.groups);
        cursor = next.next_cursor ?? undefined;
      } while (cursor);
      return result.filter((item) => item.id).sort((a, b) => a.label.localeCompare(b.label));
    }
    void Promise.all([collect('project'), collect('agent'), collect('format')]).then(([p, a, f]) => {
      if (!cancelled) { projects = p; agents = a; formats = f; }
    }).catch(() => { if (!cancelled) facetError = 'Filter choices could not be loaded. Reload to retry.'; });
    return () => { cancelled = true; };
  });
  onDestroy(() => clearTimeout(timer));
</script>

<div class="min-w-0 space-y-4" data-testid="resource-browser">
  <div class="flex flex-wrap items-end justify-between gap-3 border-b border-separator">
    <div class="flex gap-5" role="tablist" aria-label="Resource type">
      {#each [['deliverable', 'Deliverables'], ['artifact', 'Files']] as [value, label]}
        <button type="button" role="tab" aria-selected={kind === value} class={`min-h-12 border-b-2 pb-3 pt-2 text-sm font-medium ${kind === value ? 'border-accent text-accent' : 'border-transparent text-muted hover:text-foreground'}`} onclick={() => change('kind', value)}>{label}</button>
      {/each}
    </div>
    <span class="pb-3 text-xs text-quiet">Latest revision of each document</span>
    {#if $auth.user?.role !== 'viewer'}<button class="mb-2 inline-flex min-h-11 items-center gap-2 rounded-lg bg-accent px-3 text-sm text-on-accent" onclick={() => { creating = true; }}><Plus size={16} />New artifact</button>{/if}
  </div>
  <div class="flex flex-wrap items-end gap-3">
    <label class="relative block min-w-48 flex-1">
      <span class="sr-only">Search titles and filenames</span>
      <Search size={16} class="pointer-events-none absolute left-3 top-3.5 text-quiet" />
      <input use:findTarget type="search" value={search} oninput={(event) => searchChanged(event.currentTarget.value)} placeholder={kind === 'deliverable' ? 'Search deliverable titles…' : 'Search filenames…'} class="min-h-11 w-full rounded-lg border border-control-border bg-canvas/60 py-2.5 pl-10 pr-3 text-sm text-foreground outline-none focus:border-accent" />
    </label>
    <button type="button" aria-pressed={filters.favorites ?? false} onclick={() => change('favorites', filters.favorites ? '' : 'true')} class={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm ${filters.favorites ? 'border-warning-border text-warning' : 'border-control-border text-secondary'}`}><Star size={16} fill={filters.favorites ? 'currentColor' : 'none'} />Favorites</button>
    <button type="button" class={`min-h-11 rounded-lg border px-3 text-sm ${showFilters || activeFilterCount ? 'border-accent/50 text-accent' : 'border-control-border text-secondary'}`} aria-expanded={showFilters} onclick={() => { showFilters = !showFilters; }}>Filters{activeFilterCount ? ` (${activeFilterCount})` : ''}</button>
    <label class="flex min-h-11 items-center gap-2 rounded-lg border border-control-border bg-canvas/40 px-3 text-sm text-secondary">
      {#if grouping === 'none'}<List size={16} />{:else}<FolderTree size={16} />{/if}
      <span class="sr-only">View</span>
      <select value={grouping} onchange={(event) => change('group', event.currentTarget.value)} class="min-w-0 bg-transparent py-2 outline-none" aria-label="View">
        <option value="none">List</option>
        {#if !projectId}<option value="project">By project</option>{/if}
        <option value="conversation">By conversation / task</option>
        {#if !projectId}<option value="project_conversation">Project / conversation / task tree</option>{/if}
      </select>
    </label>
    <label class="text-xs text-muted">
      <span class="sr-only">Sort resources</span>
      <select aria-label="Sort resources" value={filters.sort} onchange={(event) => change('sort', event.currentTarget.value)} class="min-h-11 rounded-lg border border-control-border bg-canvas/40 px-3 text-sm">
        <option value="updated">Recently updated</option><option value="created">Recently created</option>
      </select>
    </label>
  </div>
  {#if showFilters}
    <div class="grid grid-cols-2 gap-3 rounded-lg border border-separator bg-surface/40 p-4 lg:grid-cols-4">
      {#each [
        ...(!projectId ? [{ key: 'project', label: 'Project', choices: projects.map((p) => [p.id, p.label]) }] : []),
        { key: 'agent', label: 'Agent', choices: agents.map((a) => [a.id, a.label]) },
        { key: 'ownership', label: 'Ownership', choices: [['mine', 'My work'], ['shared', 'Shared with me']] },
        { key: 'format', label: 'Format', choices: formats.map((f) => [f.id, formatLabel(f.label)]) },
        ...(kind === 'artifact' ? [{ key: 'origin', label: 'File source', choices: [['user', 'User uploads'], ['agent', 'Agent outputs'], ['other', 'Other files']] }] : []),
      ] as field (field.key)}
        <label class="min-w-0 space-y-1 text-xs text-muted">
          <span class="block">{field.label}</span>
          <select aria-label={field.label} value={param(field.key)} onchange={(event) => change(field.key, event.currentTarget.value)} class="min-h-11 w-full rounded-md border border-control-border bg-canvas px-2 text-sm text-foreground">
            <option value="">All</option>
            {#each field.choices as [value, label]}<option {value}>{label}</option>{/each}
          </select>
        </label>
      {/each}
      {#each [['after', 'Created from'], ['before', 'Created until']] as [key, label]}
        <label class="space-y-1 text-xs text-muted"><span class="block">{label}</span><input type="date" aria-label={label} value={param(key)} onchange={(event) => change(key, event.currentTarget.value)} class="min-h-11 w-full min-w-0 rounded-md border border-control-border bg-canvas px-2 text-sm text-foreground [color-scheme:dark]" /></label>
      {/each}
      <button type="button" class="self-end py-3 text-left text-xs text-accent" onclick={clearFilters}>Clear filters</button>
      {#if facetError}<p class="col-span-full text-xs text-danger" role="alert">{facetError}</p>{/if}
    </div>
  {/if}
  <div class="min-w-0 overflow-hidden rounded-xl border border-separator bg-canvas/25">
    {#if scope && readyScope === scope}{#key `${revision}:${filters.favorites ? $favoriteRevision : ''}`}<ResourceBranch {filters} levels={[...levels]} onOpen={openResource} />{/key}{:else}<p role="status" class="p-5 text-sm text-muted">Loading preferences…</p>{/if}
  </div>
  <p class="text-xs text-quiet">Search matches titles and filenames. Open a document to read its content and revision history.</p>
</div>
{#if page.url.searchParams.get('lib_item') && ['deliverable', 'artifact'].includes(page.url.searchParams.get('lib_item_kind') ?? '')}
  <ResourceModal ref={selectedRef} kind={selectedKind} onClose={closeResource} onChanged={changed} />
{/if}
{#if creating}<NewArtifactModal {projectId} onClose={() => { creating = false; }} onCreated={(item) => { creating = false; changed(item); }} />{/if}
