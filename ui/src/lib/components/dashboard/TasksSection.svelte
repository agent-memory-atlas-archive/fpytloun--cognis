<script lang="ts">
  import '$lib/dashboard/bounded-sections.css';
  import { goto } from '$app/navigation';
  import ExternalLink from 'lucide-svelte/icons/external-link';

  import AgentAvatar from '$lib/components/AgentAvatar.svelte';
  import ActivityAvatar from '$lib/components/ActivityAvatar.svelte';
  import DiffStat from '$lib/components/DiffStat.svelte';
  import WorkstreamExecutionStatus from '$lib/components/WorkstreamExecutionStatus.svelte';
  import DashboardRowIndicators from './DashboardRowIndicators.svelte';
  import DashboardRowTitle from './DashboardRowTitle.svelte';
  import Card from '$lib/components/ui/Card.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { isAttentionActionQuickAction } from '$lib/attention/actions';
  import {
    dashboardTaskRequiresAction,
    dashboardTaskWaitingReason,
    partitionTaskLanes,
    upcomingSchedules
  } from '$lib/dashboard/dashboard';
  import { formatRelativeTime } from '$lib/time';
  import {
    DASHBOARD_MOBILE_PAGE_SIZE,
    DASHBOARD_MOBILE_QUERY,
    canLoadMoreRecent,
    loadMoreRecent,
    visibleRecentItems,
  } from '$lib/dashboard/bounded-list';
  import type { Agent, AttentionActionSummary, Project, Schedule, TaskBoard, TaskBoardItem } from '$lib/types/api';

  let {
    board,
    schedules,
    agents,
    projects = [], selectedProjectId = '', onToggleProject,
    loading = false,
    error = null,
    schedulesError = null,
    onOpenTask,
    onOpenSchedule,
    onOpenAttention,
    onNewTask,
    onSeeAll = () => goto('/tasks'),
    metadataForItem,
    onRetry = () => undefined,
    onSchedulesRetry = () => undefined,
    recentHasMore = false,
    recentLoading = false,
    recentError = null,
    onLoadMoreRecent = () => undefined,
  } = $props<{
    board: TaskBoard | null;
    schedules: Schedule[] | null;
    agents: Agent[];
    projects?: Project[];
    selectedProjectId?: string;
    onToggleProject?: (id: string) => void;
    loading?: boolean;
    error?: string | null;
    schedulesError?: string | null;
    onOpenTask: (taskId: string) => void;
    onOpenSchedule: (schedule: Schedule) => void;
    onOpenAttention?: (action: AttentionActionSummary, origin: HTMLElement) => void;
    onNewTask?: () => void;
    onSeeAll?: (() => void) | null;
    metadataForItem?: (item: TaskBoardItem) => string;
    onRetry?: () => void;
    onSchedulesRetry?: () => void;
    recentHasMore?: boolean;
    recentLoading?: boolean;
    recentError?: string | null;
    onLoadMoreRecent?: () => void;
  }>();

  const lanes = $derived(partitionTaskLanes(board, Number.MAX_SAFE_INTEGER));
  const upcoming = $derived(upcomingSchedules(schedules));

  // Mobile: bounded Recent list with explicit Load more (see bounded-list.ts).
  let mobile = $state(false);
  let recentLimit = $state(DASHBOARD_MOBILE_PAGE_SIZE);
  $effect(() => {
    const query = window.matchMedia?.(DASHBOARD_MOBILE_QUERY);
    if (!query) return;
    mobile = query.matches;
    const change = (event: MediaQueryListEvent) => { mobile = event.matches; };
    query.addEventListener('change', change);
    return () => query.removeEventListener('change', change);
  });
  const recentItems = $derived(visibleRecentItems(lanes.recent, mobile, recentLimit));
  const showLoadMore = $derived(canLoadMoreRecent(lanes.recent.length, recentHasMore, mobile, recentLimit));

  function onLoadMoreClick(): void {
    recentLimit = loadMoreRecent({
      loadedCount: lanes.recent.length,
      serverHasMore: recentHasMore,
      mobile,
      limit: recentLimit,
      fetchMore: onLoadMoreRecent,
    });
  }

  function agentFor(agentId: string): Agent | undefined {
    return agents.find((agent: Agent) => agent.agent_id === agentId);
  }

  function todoProgress(item: TaskBoardItem): { total: number; completed: number; in_progress: number } {
    return {
      total: item.progress_summary?.todo_total ?? 0,
      completed: item.progress_summary?.todo_completed ?? 0,
      in_progress: item.progress_summary?.todo_in_progress ?? 0
    };
  }

  function openTaskRow(taskId: string): void {
    onOpenTask(taskId);
  }

  function handleTaskRowKeydown(event: KeyboardEvent, taskId: string): void {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    openTaskRow(taskId);
  }

  function openTaskLink(event: MouseEvent, taskId: string): void {
    event.stopPropagation();
    void goto(`/tasks/${taskId}`);
  }

  function stopRowKeyboardActivation(event: KeyboardEvent): void {
    event.stopPropagation();
  }

  function openAttention(event: MouseEvent, action: AttentionActionSummary): void {
    event.stopPropagation();
    onOpenAttention?.(action, event.currentTarget as HTMLElement);
  }

  function handleScheduleKeydown(event: KeyboardEvent, schedule: Schedule): void {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    onOpenSchedule(schedule);
  }

  function openSchedules(event: MouseEvent): void {
    event.stopPropagation();
    void goto('/schedules');
  }

  function observeRecentSentinel(node: HTMLElement): { destroy: () => void } {
    const root = node.closest('[data-testid="dashboard-tasks-recent-list"]');
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) onLoadMoreClick();
    }, { root, rootMargin: '160px 0px' });
    observer.observe(node);
    return { destroy: () => observer.disconnect() };
  }
</script>

{#snippet indicators(item: TaskBoardItem)}
  <DashboardRowIndicators {item} {projects} {selectedProjectId} {onToggleProject}
    progress={todoProgress(item)} />
{/snippet}

{#snippet rowTitle(item: TaskBoardItem)}
  <DashboardRowTitle title={item.title}
    linkLabel={`Open task ${item.title} in full page`} linkTestId={`dashboard-task-row-link-${item.task_id}`}
    onOpenLink={(event) => openTaskLink(event, item.task_id)} />
{/snippet}

<div class="dashboard-bounded-section min-w-0 md:flex md:h-full md:min-h-0 md:flex-col" data-testid="dashboard-tasks-section">
<Card class="min-w-0 p-4 md:flex md:h-full md:min-h-0 md:flex-col md:overflow-hidden">
  <div class="flex min-w-0 shrink-0 items-center justify-between gap-3">
    <h2 class="text-sm font-semibold uppercase tracking-[0.2em] text-secondary">Tasks</h2>
    <div class="flex items-center gap-2">
      {#if onNewTask}<Button size="sm" variant="secondary" data-testid="dashboard-tasks-new" onclick={onNewTask}>New task</Button>{/if}
      {#if onSeeAll}<Button size="sm" variant="ghost" data-testid="dashboard-tasks-see-all" onclick={onSeeAll}>See all</Button>{/if}
    </div>
  </div>

  {#if error}
    <p class="mt-3 shrink-0 rounded-xl border border-warning-border bg-warning-subtle p-3 text-xs text-warning" role="alert" data-testid="dashboard-tasks-error">
      Could not load tasks: {error}
      <Button class="ml-2" size="sm" variant="secondary" onclick={onRetry}>Try again</Button>
    </p>
  {:else if loading && !board}
    <p class="mt-3 shrink-0 text-xs text-quiet">Loading tasks…</p>
  {:else}
    <div class="dashboard-section-lanes mt-4 space-y-5 md:flex md:min-h-0 md:flex-1 md:flex-col md:space-y-0 md:gap-2 md:overflow-hidden">
      <section class="md:flex md:min-h-16 md:flex-col" data-testid="dashboard-tasks-running">
        <div class="flex shrink-0 items-center gap-2">
          <p class="text-xs font-medium uppercase tracking-widest text-accent">Running now</p>
          <span class="rounded-full bg-raised/70 px-1.5 py-0.5 text-[10px] tabular-nums text-muted"
            aria-label={`${lanes.running.length} running tasks`} data-testid="running-task-count">{lanes.running.length}</span>
        </div>
        {#if lanes.running.length === 0}
          <p class="mt-2 shrink-0 text-xs text-quiet">Nothing running.</p>
        {:else}
          <ul
            class="mt-2 min-h-0 space-y-1.5 md:min-h-8 md:max-h-56 md:overflow-y-auto"
            data-testid="dashboard-tasks-running-list"
            aria-label="Running tasks"
          >
            {#each lanes.running as item (item.task_id)}
              {@const summary = item.progress_summary}
              {@const progress = todoProgress(item)}
              <li>
                <div
                  role="button"
                  tabindex="0"
                  class="flex min-w-0 w-full items-center gap-3 rounded-xl border border-separator bg-canvas/40 px-3 py-2.5 text-left hover:border-accent/40"
                  data-testid={`dashboard-task-row-${item.task_id}`}
                  onclick={() => openTaskRow(item.task_id)}
                  onkeydown={(event) => handleTaskRowKeydown(event, item.task_id)}
                >
                  <ActivityAvatar
                    name={agentFor(item.agent_id)?.display_name ?? item.agent_id}
                    avatarUrl={agentFor(item.agent_id)?.avatar_url ?? null}
                    turnInProgress
                    attentionLabel={agentFor(item.agent_id)?.display_name ?? item.agent_id}
                    class="h-8 w-8"
                  />
                   <div class="min-w-0 flex-1">
                    {@render rowTitle(item)}
                    <div class="flex min-w-0 items-center gap-2">
                      <span class="shrink-0 rounded-full border border-control-border bg-surface px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-secondary">
                        P{item.priority}
                      </span>
                      <WorkstreamExecutionStatus label={item.status} active />
                    </div>
                    {#if metadataForItem}<p class="truncate text-xs text-quiet">{metadataForItem(item)}</p>{/if}
                    <div class="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted">
                      {#if summary?.current_step_name}
                        <span class="truncate text-accent">{summary.current_step_name}</span>
                        {#if summary.current_step_status && summary.current_step_status.toLowerCase() !== item.status.toLowerCase()}
                          <span>{summary.current_step_status}</span>
                        {/if}
                      {/if}
                      <span>{formatRelativeTime(item.updated_at ?? item.started_at)}</span>
                      {#if progress.total > 0}<span>{progress.completed}/{progress.total} todos</span>{/if}
                      {#if summary && (summary.changed_files > 0 || summary.additions > 0 || summary.deletions > 0)}
                        <DiffStat files={summary.changed_files} additions={summary.additions} deletions={summary.deletions} compact />
                      {/if}
                    </div>
                  </div>
                  {#each item.attention_actions ?? [] as action (action.action_id)}
                    {#if isAttentionActionQuickAction(action)}
                      <button
                        type="button"
                        aria-label={`${action.title} for ${item.title}`}
                        class="shrink-0 rounded-lg border border-warning-border bg-warning-subtle px-2 py-1.5 text-xs font-medium text-warning hover:bg-warning-subtle"
                        data-testid={`dashboard-attention-${action.action_id}`}
                        onclick={(event) => openAttention(event, action)}
                        onkeydown={stopRowKeyboardActivation}
                      >{action.title}</button>
                    {/if}
                  {/each}
                  {@render indicators(item)}
                </div>
              </li>
            {/each}
          </ul>
        {/if}
      </section>

      {#if lanes.waiting.length > 0}
        <section class="md:flex md:min-h-16 md:flex-col" data-testid="dashboard-tasks-waiting">
          <p class="shrink-0 text-xs font-medium uppercase tracking-widest text-warning">Paused / waiting</p>
          <ul
            class="mt-2 min-h-0 space-y-1.5 md:min-h-8 md:max-h-56 md:overflow-y-auto"
            data-testid="dashboard-tasks-waiting-list"
            aria-label="Paused or waiting tasks"
          >
            {#each lanes.waiting as item (item.task_id)}
              <li>
                <div
                  role="button"
                  tabindex="0"
                  class="flex min-w-0 w-full items-center gap-3 rounded-xl border border-warning-border bg-warning-subtle px-3 py-2 text-left hover:border-warning-border"
                  data-testid={`dashboard-task-row-${item.task_id}`}
                  onclick={() => openTaskRow(item.task_id)}
                  onkeydown={(event) => handleTaskRowKeydown(event, item.task_id)}
                >
                  <AgentAvatar name={agentFor(item.agent_id)?.display_name ?? item.agent_id} avatarUrl={agentFor(item.agent_id)?.avatar_url ?? null} class="h-8 w-8" />
                  <div class="min-w-0 flex-1">
                    {@render rowTitle(item)}
                    {#if metadataForItem}<p class="truncate text-xs text-quiet">{metadataForItem(item)}</p>{/if}
                    <div class="mt-0.5 flex items-center gap-2 text-xs">
                       <WorkstreamExecutionStatus label={dashboardTaskRequiresAction(item) ? 'Action required' : 'Paused'} />
                      <span class="truncate text-warning" data-testid={`dashboard-task-waiting-reason-${item.task_id}`}>
                        {dashboardTaskWaitingReason(item)}
                      </span>
                      <span class="shrink-0 text-quiet">{formatRelativeTime(item.updated_at)}</span>
                    </div>
                   </div>
                  {#each item.attention_actions ?? [] as action (action.action_id)}
                    {#if isAttentionActionQuickAction(action)}
                      <button
                        type="button"
                        aria-label={`${action.title} for ${item.title}`}
                        class="shrink-0 rounded-lg border border-warning-border bg-warning-subtle px-2 py-1.5 text-xs font-medium text-warning hover:bg-warning-subtle"
                        data-testid={`dashboard-attention-${action.action_id}`}
                        onclick={(event) => openAttention(event, action)}
                        onkeydown={stopRowKeyboardActivation}
                      >{action.title}</button>
                    {/if}
                  {/each}
                  {@render indicators(item)}
                </div>
              </li>
            {/each}
          </ul>
        </section>
      {/if}

      <section class="md:flex md:min-h-16 md:flex-col" data-testid="dashboard-tasks-upcoming">
        <p class="shrink-0 text-xs font-medium uppercase tracking-widest text-muted">Upcoming schedules</p>
        {#if schedulesError}
          <p class="mt-2 shrink-0 text-xs text-warning" role="alert" data-testid="dashboard-schedules-error">
            Could not load schedules: {schedulesError}
            <Button class="ml-2" size="sm" variant="secondary" onclick={onSchedulesRetry}>Try again</Button>
          </p>
        {:else if upcoming.length === 0}
          <p class="mt-2 shrink-0 text-xs text-quiet">No upcoming schedules.</p>
        {:else}
          <ul
            class="mt-2 min-h-0 space-y-1.5 md:min-h-8 md:max-h-56 md:overflow-y-auto"
            data-testid="dashboard-tasks-upcoming-list"
            aria-label="Upcoming schedules"
          >
            {#each upcoming as schedule (schedule.schedule_id)}
              <li>
              <div
                class="flex min-w-0 cursor-pointer items-center gap-3 rounded-xl border border-separator bg-canvas/40 px-3 py-2 text-xs hover:border-accent/40"
                data-testid={`dashboard-schedule-row-${schedule.schedule_id}`}
                role="button"
                tabindex="0"
                onclick={() => onOpenSchedule(schedule)}
                onkeydown={(event) => handleScheduleKeydown(event, schedule)}
              >
                <span data-testid={`dashboard-schedule-agent-${schedule.schedule_id}`}>
                  <AgentAvatar name={agentFor(schedule.agent_id)?.display_name ?? schedule.agent_id} avatarUrl={agentFor(schedule.agent_id)?.avatar_url ?? null} class="h-8 w-8" />
                </span>
                <span class="min-w-0 flex-1 truncate text-foreground">{schedule.name}</span>
                <span class="shrink-0 text-muted">{formatRelativeTime(schedule.next_fire_at)}</span>
                <button
                  type="button"
                  aria-label={`Open schedule ${schedule.name} in full page`}
                  class="shrink-0 rounded-lg p-1.5 text-quiet hover:bg-raised hover:text-strong"
                  data-testid={`dashboard-schedule-row-link-${schedule.schedule_id}`}
                  onclick={openSchedules}
                  onkeydown={stopRowKeyboardActivation}
                >
                  <ExternalLink class="h-3.5 w-3.5" />
                </button>
              </div>
              </li>
            {/each}
          </ul>
        {/if}
      </section>

      <section class="dashboard-section-recent flex min-h-0 flex-col md:min-h-20 md:flex-1" data-testid="dashboard-tasks-recent">
        <p class="shrink-0 text-xs font-medium uppercase tracking-widest text-muted">Recent</p>
        {#if lanes.recent.length === 0}
          <p class="mt-2 shrink-0 text-xs text-quiet">No recently finished tasks.</p>
        {:else}
          <ul
            class="mt-2 min-h-0 space-y-1.5 md:flex-1 md:overflow-y-auto"
            data-testid="dashboard-tasks-recent-list"
            aria-label="Recently finished tasks"
          >
            {#each recentItems as item (item.task_id)}
              <li>
                <div
                  role="button"
                  tabindex="0"
                  class="flex min-w-0 w-full items-center gap-3 rounded-xl border border-separator bg-canvas/40 px-3 py-2 text-left hover:border-accent/40"
                  data-testid={`dashboard-task-row-${item.task_id}`}
                  onclick={() => openTaskRow(item.task_id)}
                  onkeydown={(event) => handleTaskRowKeydown(event, item.task_id)}
                >
                  <AgentAvatar name={agentFor(item.agent_id)?.display_name ?? item.agent_id} avatarUrl={agentFor(item.agent_id)?.avatar_url ?? null} class="h-8 w-8" />
                  <div class="min-w-0 flex-1">
                    {@render rowTitle(item)}
                    {#if metadataForItem}<p class="truncate text-xs text-quiet">{metadataForItem(item)}</p>{/if}
                    <p class="truncate text-xs text-muted">
                      {item.status} · {formatRelativeTime(item.completed_at ?? item.updated_at)}
                      {#if item.result_summary} · {item.result_summary}{/if}
                    </p>
                  </div>
                  {@render indicators(item)}
                </div>
              </li>
            {/each}
            {#if showLoadMore && !recentLoading && !recentError}
              {#key recentItems.length}
                <li use:observeRecentSentinel aria-hidden="true" data-testid="dashboard-tasks-recent-sentinel" class="h-px"></li>
              {/key}
            {/if}
            {#if recentLoading}<li class="py-2 text-center text-xs text-quiet">Loading…</li>{/if}
            {#if recentError}<li class="py-2 text-xs text-warning" role="alert">{recentError}</li>{/if}
          </ul>
        {/if}
        {#if recentHasMore && !recentLoading && !recentError && lanes.recent.length === 0}
          <div use:observeRecentSentinel aria-hidden="true" data-testid="dashboard-tasks-recent-sentinel" class="h-px"></div>
        {/if}
        {#if showLoadMore}<Button size="sm" variant="ghost" disabled={recentLoading} onclick={onLoadMoreClick} data-testid="dashboard-tasks-load-more">{recentError ? 'Retry loading tasks' : 'Load more tasks'}</Button>{/if}
      </section>
    </div>
  {/if}
</Card>
</div>
