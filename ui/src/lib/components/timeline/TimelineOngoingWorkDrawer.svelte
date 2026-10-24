<script lang="ts">
  import { chatNavigation, followConversationLink } from '$lib/chat-v2/navigation';
  const navigation = chatNavigation();
  import ChevronDown from 'lucide-svelte/icons/chevron-down';
  import ChevronUp from 'lucide-svelte/icons/chevron-up';
  import ExternalLink from 'lucide-svelte/icons/external-link';
  import LoaderCircle from 'lucide-svelte/icons/loader-circle';
  import TodoProgressPopover from '$lib/components/TodoProgressPopover.svelte';
  import TodoStatusDot from '$lib/components/TodoStatusDot.svelte';
  import BackgroundCommandDetails from './BackgroundCommandDetails.svelte';
  import { backgroundWorkItemIsRunning, sortBackgroundWorkByActivity } from '$lib/ongoing-work';
  import type { TodoSnapshotItem } from '$lib/todos';
  import type { BackgroundWorkItem } from '$lib/types/api';

  let {
    todos,
    work,
    truncated = false,
    open = $bindable(false),
    onViewSession,
  } = $props<{
    todos: TodoSnapshotItem[];
    work: BackgroundWorkItem[];
    truncated?: boolean;
    open?: boolean;
    onViewSession?: (sessionId: string) => void;
  }>();

  const activeTodos = $derived(todos.filter((todo: TodoSnapshotItem) => !['completed', 'cancelled'].includes(todo.status)));
  let expandedCommandId = $state<string | null>(null);
  const runningWork = $derived(work.filter(backgroundWorkItemIsRunning));
  const commandWork = $derived(sortBackgroundWorkByActivity(
    work.filter((item: BackgroundWorkItem) => item.kind === 'background_command'),
  ));
  const taskWork = $derived(sortBackgroundWorkByActivity(
    work.filter((item: BackgroundWorkItem) => item.kind === 'task'),
  ));
  const sessionWork = $derived(sortBackgroundWorkByActivity(
    work.filter((item: BackgroundWorkItem) => item.kind !== 'background_command' && item.kind !== 'task'),
  ));

  function statusClass(status: string): string {
    if (status === 'complete' || status === 'completed') return 'text-success';
    if (status === 'error' || status === 'failed' || status === 'cancelled' || status === 'interrupted' || status === 'killed') return 'text-danger';
    if (status === 'active' || status === 'idle') return 'text-muted';
    return 'text-info';
  }

  function viewSession(sessionId: string | null | undefined): void {
    if (sessionId) onViewSession?.(sessionId);
  }
</script>

{#if todos.length > 0 || work.length > 0}
  <section class="rounded-xl border border-separator bg-surface/40">
    <button
      class="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm transition hover:bg-surface-hover"
      type="button"
      aria-expanded={open}
      onclick={() => { open = !open; }}
    >
      <span class="scrollbar-hidden-x min-w-0 text-secondary">
        <span class="font-medium text-foreground">Ongoing work</span>
        <span class="text-quiet">
          {#if runningWork.length > 0} · {runningWork.length} running{/if}
          {#if taskWork.length > 0} · {taskWork.length} task{taskWork.length === 1 ? '' : 's'}{/if}
          {#if sessionWork.length > 0} · {sessionWork.length} session{sessionWork.length === 1 ? '' : 's'}{/if}
          {#if commandWork.length > 0} · {commandWork.length} command{commandWork.length === 1 ? '' : 's'}{/if}
          {#if activeTodos.length > 0} · {activeTodos.length} todo{activeTodos.length === 1 ? '' : 's'}{/if}
        </span>
      </span>
      <span class="flex shrink-0 items-center gap-2">
        {#if runningWork.length > 0}
          <LoaderCircle class="h-3.5 w-3.5 animate-spin text-info" aria-label="Background work active" />
        {/if}
        {#if open}
          <ChevronUp class="h-3.5 w-3.5 text-quiet" />
        {:else}
          <ChevronDown class="h-3.5 w-3.5 text-quiet" />
        {/if}
      </span>
    </button>

    {#if open}
      <div class={`grid w-full max-w-full grid-cols-[minmax(0,1fr)] max-h-[45vh] min-h-0 min-w-0 gap-3 overflow-x-hidden overflow-y-auto border-t border-separator p-3 lg:max-h-72 lg:overflow-hidden ${work.length > 0 ? 'lg:grid-cols-2' : ''}`}>
        <div class="min-h-0 min-w-0">
          <p class="mb-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-quiet">Todos</p>
          {#if todos.length > 0}
            <ul class="min-w-0 divide-y divide-separator overflow-x-hidden overflow-y-auto rounded-lg border border-separator lg:max-h-60">
              {#each todos as todo}
                <li class="flex items-center gap-2 px-3 py-2 text-sm text-foreground">
                  <TodoStatusDot status={todo.status} />
                  <span class="scrollbar-hidden-x min-w-0 flex-1" title={todo.content}>{todo.content}</span>
                </li>
              {/each}
            </ul>
          {:else}
            <p class="rounded-lg border border-dashed border-separator px-3 py-4 text-xs text-quiet">No todos in this conversation.</p>
          {/if}
        </div>

        {#if work.length > 0}
        <div class="min-h-0 min-w-0">
          <div class="mb-2 flex items-center justify-between gap-2">
            <p class="text-[10px] font-semibold uppercase tracking-[0.2em] text-quiet">
              {taskWork.length > 0 && sessionWork.length === 0 && commandWork.length === 0
                ? 'Tasks'
                : 'Tasks, sessions, and commands'}
            </p>
            {#if truncated}<span class="text-[10px] text-warning">Some global work is omitted</span>{/if}
          </div>
          <div class="min-w-0 space-y-1.5 overflow-x-hidden overflow-y-auto lg:max-h-60">
            {#each [...taskWork, ...sessionWork, ...commandWork] as item (item.work_id)}
              <article class="w-full max-w-full min-w-0 overflow-hidden rounded-lg border border-separator bg-inset/35 px-3 py-2">
                {#if item.kind === 'background_command'}
                  <button type="button" class="min-h-10 w-full min-w-0 break-words text-left text-sm font-medium text-accent hover:text-accent-hover" aria-expanded={expandedCommandId === item.work_id} onclick={() => { expandedCommandId = expandedCommandId === item.work_id ? null : item.work_id; }}>
                    {item.title}
                  </button>
                {:else if item.kind === 'task' && item.task_id}
                  <a class="flex min-h-10 min-w-0 items-center break-words text-sm font-medium text-accent hover:text-accent-hover" href={`/tasks/${item.task_id}`}>{item.title}</a>
                {:else if item.kind === 'managed_conversation' && item.target_conversation_id}
                  <a class="flex min-h-10 min-w-0 items-center break-words text-sm font-medium text-accent hover:text-accent-hover" href={`/chat/${item.target_conversation_id}`} onclick={(event) => followConversationLink(event, item.target_conversation_id!, navigation)}>{item.title}</a>
                {:else if item.session_id && onViewSession}
                  <button type="button" class="min-h-10 w-full min-w-0 break-words text-left text-sm font-medium text-accent hover:text-accent-hover" onclick={() => viewSession(item.session_id)}>{item.title}</button>
                {:else}
                  <p class="break-words text-sm font-medium text-foreground">{item.title}</p>
                {/if}
                <div class="mt-1 flex w-full max-w-full min-w-0 items-center gap-2">
                  {#if item.kind !== 'background_command' && item.kind !== 'task'}
                    <TodoProgressPopover todos={item.todos} size="sm" class="shrink-0 text-success" label={`${item.title} todo progress`} />
                  {/if}
                  <p class="scrollbar-hidden-x min-w-0 flex-1 text-xs text-quiet" title={`${item.agent_id}${item.agent_profile_id ? ` · ${item.agent_profile_id}` : ''}`}>
                    {item.agent_id}{#if item.agent_profile_id}<span> · {item.agent_profile_id}</span>{/if}
                  </p>
                  <span class={`shrink-0 text-[10px] font-semibold uppercase tracking-wide ${statusClass(item.status)}`}>{item.status}</span>
                  {#if item.kind === 'task' && item.task_id}
                    <a class="inline-flex shrink-0 items-center text-accent hover:text-accent-hover" aria-label={`Open ${item.title}`} href={`/tasks/${item.task_id}`}>
                      <ExternalLink class="h-3.5 w-3.5" />
                    </a>
                  {:else if item.kind === 'managed_conversation' && item.target_conversation_id}
                    <a class="inline-flex shrink-0 items-center text-accent hover:text-accent-hover" aria-label={`Open ${item.title}`} href={`/chat/${item.target_conversation_id}`}>
                      <ExternalLink class="h-3.5 w-3.5" />
                    </a>
                  {:else if item.kind !== 'background_command' && item.session_id && onViewSession}
                    <button class="inline-flex shrink-0 items-center text-accent hover:text-accent-hover" aria-label={`Open ${item.title}`} type="button" onclick={() => viewSession(item.session_id)}>
                      <ExternalLink class="h-3.5 w-3.5" />
                    </button>
                  {/if}
                </div>
                {#if item.kind === 'background_command' && expandedCommandId === item.work_id}
                  <BackgroundCommandDetails {item} {onViewSession} />
                {/if}
              </article>
            {/each}
          </div>
        </div>
        {/if}
      </div>
    {/if}
  </section>
{/if}
