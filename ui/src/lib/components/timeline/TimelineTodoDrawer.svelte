<script lang="ts">
  import { onMount } from 'svelte';
  import ChevronDown from 'lucide-svelte/icons/chevron-down';
  import ChevronUp from 'lucide-svelte/icons/chevron-up';
  import TodoStatusDot from '$lib/components/TodoStatusDot.svelte';
  import type { TodoSnapshotItem } from '$lib/timeline-render-model';

  let {
    todos,
    open = $bindable(true)
  } = $props<{
    todos: TodoSnapshotItem[];
    open?: boolean;
  }>();

  const terminalTodoStatuses = new Set(['completed', 'cancelled']);
  const compactDrawerMaxWidthPx = 1023;
  const compactDrawerMaxHeightPx = 719;

  let compactViewport = $state(true);
  let lastAutoOpenKey = $state('');
  const activeTodos = $derived.by(() => todos.filter((todo: TodoSnapshotItem) => !terminalTodoStatuses.has(todo.status)));
  const todoCounts = $derived.by(() => ({
    inProgress: activeTodos.filter((todo: TodoSnapshotItem) => todo.status === 'in_progress').length,
    pending: activeTodos.filter((todo: TodoSnapshotItem) => todo.status === 'pending').length,
  }));

  function isCompactViewport(): boolean {
    return window.innerWidth <= compactDrawerMaxWidthPx || window.innerHeight <= compactDrawerMaxHeightPx;
  }

  function refreshCompactViewport(): void {
    compactViewport = isCompactViewport();
  }

  onMount(() => {
    refreshCompactViewport();
    window.addEventListener('resize', refreshCompactViewport);
    window.visualViewport?.addEventListener('resize', refreshCompactViewport);
    return () => {
      window.removeEventListener('resize', refreshCompactViewport);
      window.visualViewport?.removeEventListener('resize', refreshCompactViewport);
    };
  });

  $effect(() => {
    if (todos.length === 0) {
      lastAutoOpenKey = '';
      return;
    }

    const autoOpenKey = compactViewport ? 'compact' : 'roomy';
    if (autoOpenKey !== lastAutoOpenKey) {
      open = !compactViewport;
      lastAutoOpenKey = autoOpenKey;
    }
  });
</script>

{#if todos.length > 0}
  <div class="rounded-xl border border-separator bg-surface/40">
    <button
      class="flex w-full items-center justify-between gap-3 px-3 py-1.5 text-left text-sm transition hover:bg-surface-hover"
      onclick={() => { open = !open; }}
      type="button"
    >
      <span class="scrollbar-hidden-x min-w-0 text-secondary">
        <span class="font-medium text-foreground">Todos</span>
        <span class="text-quiet"> · {activeTodos.length} active{#if todoCounts.inProgress > 0} · {todoCounts.inProgress} in progress{/if}{#if todoCounts.pending > 0} · {todoCounts.pending} pending{/if}</span>
      </span>
      {#if open}
        <ChevronUp class="h-3.5 w-3.5 shrink-0 text-quiet" />
      {:else}
        <ChevronDown class="h-3.5 w-3.5 shrink-0 text-quiet" />
      {/if}
    </button>
    {#if open}
      <ul class="divide-y divide-separator border-t border-separator">
        {#each todos as todo}
          <li class="flex items-center gap-2 px-3 py-1.5 text-sm text-foreground">
            <TodoStatusDot status={todo.status} />
            <span class="scrollbar-hidden-x min-w-0 flex-1">{todo.content}</span>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}
