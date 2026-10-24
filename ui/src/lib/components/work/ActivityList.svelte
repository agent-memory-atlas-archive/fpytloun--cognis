<script lang="ts">
  import { onDestroy } from 'svelte';
  import ArrowRight from 'lucide-svelte/icons/arrow-right';
  import BriefcaseBusiness from 'lucide-svelte/icons/briefcase-business';
  import RefreshCw from 'lucide-svelte/icons/refresh-cw';

  import { ChatV2ApiError, chatV2Api } from '$lib/chat-v2/api';
  import type { WorkActivityItem, WorkActivityListResponse } from '$lib/chat-v2/types';
  import { formatAbsoluteTime, formatRelativeTime } from '$lib/time';
  import { useSectionConnectivity } from '$lib/connectivity-section.svelte';

  type WorkActivitiesLoader = (
    options: { limit: number; cursor: string | null; signal: AbortSignal },
  ) => Promise<WorkActivityListResponse>;

  const defaultLoader: WorkActivitiesLoader = ({ limit, cursor, signal }) =>
    chatV2Api.workActivities({ limit, cursor, signal });

  let {
    onSelect,
    loadActivities = defaultLoader,
  } = $props<{
    onSelect: (item: WorkActivityItem) => void;
    loadActivities?: WorkActivitiesLoader;
  }>();

  let items = $state<WorkActivityItem[]>([]);
  let nextCursor = $state<string | null>(null);
  let hasMore = $state(false);
  let loading = $state(true);
  let loadingMore = $state(false);
  let error = $state<string | null>(null);
  let failedReplace = $state(false);
  // Hidden while the global connection banner applies; reload on restore.
  const net = useSectionConnectivity({ hasError: () => Boolean(error), retry: () => load(failedReplace || items.length === 0) });
  let controller: AbortController | null = null;
  let generation = 0;

  const itemKey = (item: WorkActivityItem): string =>
    `${item.activity_scope_id}:${item.scope.key}`;
  const accessibleId = (item: WorkActivityItem): string =>
    encodeURIComponent(itemKey(item));

  async function load(replace: boolean): Promise<void> {
    if (!replace && (loading || loadingMore)) return;
    controller?.abort();
    const requestController = new AbortController();
    controller = requestController;
    const requestGeneration = ++generation;
    if (replace) loading = true;
    else loadingMore = true;
    error = null;
    try {
      const response = await loadActivities({
        limit: 20,
        cursor: replace ? null : nextCursor,
        signal: requestController.signal,
      });
      if (requestController.signal.aborted || requestGeneration !== generation) return;
      const seen = new Set((replace ? [] : items).map(itemKey));
      const accepted = response.items.filter((item: WorkActivityItem) => {
        const key = itemKey(item);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
      items = replace ? accepted : [...items, ...accepted];
      nextCursor = response.next_cursor ?? null;
      hasMore = response.has_more && nextCursor !== null;
    } catch (nextError) {
      if (requestController.signal.aborted || requestGeneration !== generation) return;
      error = nextError instanceof ChatV2ApiError || nextError instanceof Error
        ? nextError.message
        : 'Work activities are temporarily unavailable.';
      failedReplace = replace;
    } finally {
      if (requestGeneration === generation) {
        loading = false;
        loadingMore = false;
      }
    }
  }

  $effect(() => {
    void load(true);
  });

  onDestroy(() => {
    generation += 1;
    controller?.abort();
  });
</script>

<section class="mx-auto w-full max-w-5xl space-y-4" aria-labelledby="work-activities-title">
  <header class="flex flex-wrap items-center justify-between gap-3">
    <div>
      <h1 id="work-activities-title" class="text-xl font-semibold text-strong">Work</h1>
      <p class="mt-1 text-sm text-muted">Recent activities across conversations and tasks.</p>
    </div>
    <button
      type="button"
      class="inline-flex min-h-10 items-center gap-2 rounded-lg border border-control-border px-3 text-sm text-foreground hover:bg-raised disabled:opacity-50"
      onclick={() => void load(true)}
      disabled={loading}
      aria-label="Refresh Work activities"
    >
      <RefreshCw class={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
      Refresh
    </button>
  </header>

  {#if (loading || (error && net.hideErrors)) && items.length === 0}
    <div class="rounded-xl border border-separator bg-surface/50 p-8 text-center text-sm text-muted" role="status" data-testid="work-activities-loading">
      Loading Work activities…
    </div>
  {:else if error && items.length === 0}
    <div class="rounded-xl border border-danger-border bg-danger-subtle p-6 text-center" role="alert" data-testid="work-activities-error">
      <p class="text-sm text-danger">{error}</p>
      <button type="button" class="mt-3 text-sm text-accent underline" onclick={() => void load(true)}>Retry</button>
    </div>
  {:else if items.length === 0}
    <div class="rounded-xl border border-dashed border-control-border p-10 text-center" data-testid="work-activities-empty">
      <BriefcaseBusiness class="mx-auto h-8 w-8 text-quiet" aria-hidden="true" />
      <p class="mt-3 text-sm text-secondary">No Work activities yet.</p>
    </div>
  {:else}
    <ul class="grid gap-3 sm:grid-cols-2" data-testid="work-activities-list">
      {#each items as item (itemKey(item))}
        <li>
          <button
            type="button"
            class="group flex min-h-32 w-full flex-col rounded-xl border border-separator bg-surface/60 p-4 text-left hover:border-accent/40 hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            onclick={() => onSelect(item)}
            data-testid={`work-activity-${item.activity_scope_id}`}
            aria-labelledby={`work-activity-title-${accessibleId(item)}`}
            aria-describedby={`work-activity-owner-${accessibleId(item)} work-activity-metadata-${accessibleId(item)}`}
          >
            <span class="flex w-full items-start gap-3">
              {#if item.agent.avatar_url}
                <img class="h-9 w-9 rounded-full object-cover" src={item.agent.avatar_url} alt="" />
              {:else}
                <span class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-accent-subtle text-sm font-semibold text-accent" aria-hidden="true">
                  {item.agent.display_name.slice(0, 1).toUpperCase()}
                </span>
              {/if}
              <span class="min-w-0 flex-1">
                <span id={`work-activity-title-${accessibleId(item)}`} class="block truncate text-sm font-medium text-foreground">{item.root.title ?? 'Untitled activity'}</span>
                <span id={`work-activity-owner-${accessibleId(item)}`} class="mt-0.5 block truncate text-xs text-muted">
                  {item.agent.display_name}{item.project ? ` · ${item.project.name}` : ''}
                </span>
              </span>
              <ArrowRight class="h-4 w-4 shrink-0 text-quiet group-hover:text-accent-hover" aria-hidden="true" />
            </span>
            <span id={`work-activity-metadata-${accessibleId(item)}`} class="mt-3 flex w-full flex-wrap items-center gap-2 text-[11px]">
              <span class="rounded-full bg-raised px-2 py-0.5 text-secondary">{item.status}</span>
              {#if item.materialization === 'absent'}
                <span class="text-quiet" data-testid="work-activity-materializing">Materializes when opened</span>
              {:else if item.summary}
                <span class="text-muted">{item.summary.changed_files} files · {item.summary.commands} commands</span>
              {/if}
              <time class="ml-auto text-quiet" datetime={item.last_activity_at} title={formatAbsoluteTime(item.last_activity_at)}>
                {formatRelativeTime(item.last_activity_at)}
              </time>
            </span>
          </button>
        </li>
      {/each}
    </ul>

    {#if error && !net.hideErrors}
      <div class="rounded-lg border border-danger-border bg-danger-subtle px-3 py-2 text-sm text-danger" role="alert">
        <span>{error} </span>
        <button type="button" class="underline" onclick={() => void load(failedReplace)}>
          {failedReplace ? 'Retry refresh' : 'Retry loading more'}
        </button>
      </div>
    {/if}
    {#if hasMore}
      <button
        type="button"
        class="mx-auto flex min-h-10 items-center rounded-lg border border-control-border px-4 text-sm text-accent hover:bg-raised disabled:opacity-50"
        onclick={() => void load(false)}
        disabled={loading || loadingMore}
        data-testid="work-activities-more"
      >
        {loadingMore ? 'Loading more…' : 'Load more'}
      </button>
    {/if}
  {/if}
</section>
