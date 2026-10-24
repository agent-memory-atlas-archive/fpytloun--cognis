<script lang="ts">
  import { api } from '$lib/api/client';
  import Folder from 'lucide-svelte/icons/folder';
  import MessageSquare from 'lucide-svelte/icons/message-square';
  import ChevronRight from 'lucide-svelte/icons/chevron-right';
  import ListTodo from 'lucide-svelte/icons/list-todo';
  import ResourceRow from './ResourceRow.svelte';
  import ResourceBranch from './ResourceBranch.svelte';
  import type { LibraryFilters, LibraryGroup, LibraryItem } from '$lib/library';

  let { filters, levels = [], onOpen }: { filters: LibraryFilters; levels?: ('project' | 'conversation')[]; onOpen?: (item: LibraryItem) => void } = $props();
  let items = $state<LibraryItem[]>([]);
  let groups = $state<LibraryGroup[]>([]);
  let expanded = $state<Set<string>>(new Set());
  let loading = $state(false);
  let error = $state('');
  let cursor = $state<string | null>(null);
  let generation = 0;
  const storageKey = () => `cognis.library.folders:${JSON.stringify([filters, levels])}`;
  async function load(append = false) {
    const current = ++generation;
    loading = true;
    error = '';
    try {
      if (levels.length) {
        const result = await api.library.groups(filters, levels[0], append ? cursor ?? undefined : undefined);
        if (current !== generation) return;
        groups = append ? [...groups, ...result.groups] : result.groups;
        cursor = result.next_cursor;
      } else {
        const result = await api.library.list(filters, append ? cursor ?? undefined : undefined);
        if (current !== generation) return;
        items = append ? [...items, ...result.items] : result.items;
        cursor = result.next_cursor;
      }
    } catch (caught) {
      if (current === generation) error = caught instanceof Error ? caught.message : 'Could not load resources.';
    } finally {
      if (current === generation) loading = false;
    }
  }
  $effect(() => {
    // Track only query inputs, not the loading state modified by load().
    const key = JSON.stringify([filters, levels]);
    void key;
    items = [];
    groups = [];
    try {
      const saved: unknown = JSON.parse(sessionStorage.getItem(storageKey()) ?? '[]');
      expanded = new Set(Array.isArray(saved) ? saved.filter((id): id is string => typeof id === 'string') : []);
    } catch { expanded = new Set(); }
    void load();
    return () => { generation += 1; };
  });
  function toggle(id: string) {
    const next = new Set(expanded);
    if (next.has(id)) next.delete(id); else next.add(id);
    expanded = next;
    try { sessionStorage.setItem(storageKey(), JSON.stringify([...next])); } catch { /* Browsing remains available without storage. */ }
  }
</script>

<div class="min-w-0" aria-busy={loading}>
  {#each groups as group (group.id)}
    <div class="min-w-0 border-b border-separator/70">
      <button type="button" class="flex min-h-14 w-full items-center gap-3 px-3 py-3 text-left hover:bg-raised/40 focus-visible:outline focus-visible:outline-accent sm:px-4" aria-expanded={expanded.has(group.id)} onclick={() => toggle(group.id)}>
        <ChevronRight size={16} class={`shrink-0 text-quiet ${expanded.has(group.id) ? 'rotate-90' : ''}`} />
        {#if levels[0] === 'project'}<Folder size={19} class="shrink-0 text-accent" />{:else if group.id.startsWith('task:')}<ListTodo size={18} class="shrink-0 text-muted" />{:else}<MessageSquare size={18} class="shrink-0 text-muted" />{/if}
        <span class="min-w-0 flex-1 break-words text-sm font-medium text-foreground">{group.label}</span>
        <span class="shrink-0 text-xs tabular-nums text-quiet">{group.count}</span>
      </button>
      {#if expanded.has(group.id)}
        <div class="ml-4 min-w-0 border-l border-control-border/70 sm:ml-7">
          <ResourceBranch filters={{ ...filters, [levels[0] === 'conversation' ? 'source_id' : 'project_id']: group.id }} levels={levels.slice(1)} {onOpen} />
        </div>
      {/if}
    </div>
  {/each}
  {#each items as item (item.id)}<ResourceRow {item} {onOpen} />{/each}
  {#if error}
    <div role="alert" class="p-5 text-sm text-danger">{error} <button class="ml-2 underline" onclick={() => load(items.length > 0 || groups.length > 0)}>Retry</button></div>
  {:else if loading}
    <p class="p-5 text-sm text-muted" role="status">Loading resources…</p>
  {:else if !items.length && !groups.length}
    <div class="px-5 py-12 text-center">
      <p class="text-sm font-medium text-secondary">No matching resources</p>
      <p class="mt-2 text-xs text-quiet">Try another search or clear the filters. Temporary uploads and internal tool files are not listed.</p>
    </div>
  {/if}
  {#if cursor && !loading && !error}
    <button type="button" class="min-h-12 w-full px-4 py-3 text-sm text-accent hover:bg-raised/40" onclick={() => load(true)}>Load more {levels.length ? 'folders' : 'resources'}</button>
  {/if}
</div>
