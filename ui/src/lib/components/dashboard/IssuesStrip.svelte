<script lang="ts">
  import { goto } from '$app/navigation';

  import Card from '$lib/components/ui/Card.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import ExecutorRuntimeDiagnostics from '$lib/components/executors/ExecutorRuntimeDiagnostics.svelte';
  import { api, asApiError } from '$lib/api/client';
  import { auth } from '$lib/stores/auth';
  import { confirmAction } from '$lib/stores/confirm';
  import { loadProviderMonitor } from '$lib/provider-monitor';
  import { summarizeDashboardIssues } from '$lib/dashboard/dashboard';
  import type { DashboardIssue, DashboardIssuesResponse } from '$lib/types/api';

  let {
    issues,
    loading = false,
    error = null,
    onRetry = () => undefined,
    onDismiss = () => undefined,
  } = $props<{
    issues: DashboardIssuesResponse | null;
    loading?: boolean;
    error?: string | null;
    onRetry?: () => void;
    onDismiss?: () => void | Promise<void>;
  }>();
  let dismissing = $state<string | null>(null);
  let leavingIssue = $state<string | null>(null);
  let dismissError = $state<string | null>(null);
  let expandedIssues = $state<string[]>([]);
  let busyAction = $state<string | null>(null);
  let actionError = $state<string | null>(null);
  const canMutate = $derived(Boolean($auth.user && $auth.user.role !== 'viewer'));

  async function retryTask(issue: DashboardIssue): Promise<void> {
    if (!canMutate || busyAction || !issue.task_id || !issue.task_retry_available) return;
    busyAction = issue.id;
    actionError = null;
    const actor = $auth.user?.email;
    try {
      const confirmed = await confirmAction({
        title: 'Retry failed task?',
        message: 'This starts a fresh run. Actions completed by the previous run may execute again. The schedule remains unchanged.',
        confirmLabel: 'Retry task',
      });
      if (!confirmed || actor !== $auth.user?.email || !canMutate) return;
      const result = await api.tasks.rerun(issue.task_id);
      if (actor === $auth.user?.email) await goto(`/tasks/${encodeURIComponent(result.task_id)}`);
    } catch (caught) {
      actionError = asApiError(caught).message || 'Could not retry the task.';
    } finally {
      busyAction = null;
    }
  }

  async function refreshProvider(issue: DashboardIssue): Promise<void> {
    if (!canMutate || busyAction || issue.resource.type !== 'llm_provider') return;
    busyAction = issue.id;
    actionError = null;
    const actor = $auth.user?.email;
    try {
      await loadProviderMonitor(issue.resource.id, true);
      if (actor === $auth.user?.email) await onDismiss();
    } catch (caught) {
      actionError = asApiError(caught).message || 'Could not refresh provider status.';
    } finally {
      busyAction = null;
    }
  }

  const summary = $derived(summarizeDashboardIssues(issues));
  const actionableIssues = $derived(issues?.issues ?? []);
  const toneClasses: Record<string, string> = {
    healthy: 'border-success-border bg-success-subtle text-success',
    info: 'border-accent/30 bg-accent-subtle text-accent',
    warning: 'border-warning-border bg-warning-subtle text-warning',
    critical: 'border-danger-border bg-danger-subtle text-danger'
  };
  const severityDot: Record<string, string> = {
    critical: 'bg-danger',
    warning: 'bg-warning',
    info: 'bg-accent'
  };

  function openAction(issue: DashboardIssue): void {
    void goto(issue.action_url);
  }
  function openTask(issue: DashboardIssue): void {
    if (issue.task_id) void goto(`/tasks/${encodeURIComponent(issue.task_id)}`);
  }

  async function dismiss(issue: DashboardIssue): Promise<void> {
    if (issue.resource.type !== 'schedule' || !issue.dismiss_token) return;
    dismissing = issue.id;
    dismissError = null;
    try {
      await api.dashboard.dismissScheduleIssue(issue.resource.id, issue.dismiss_token);
      leavingIssue = issue.id;
      if (!(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false)) {
        await new Promise((resolve) => window.setTimeout(resolve, 140));
      }
      if (issues) {
        const remaining = issues.issues.filter((item: DashboardIssue) => item.id !== issue.id);
        issues = {
          ...issues,
          issues: remaining,
          summary: {
            ...issues.summary,
            total: Math.max(0, issues.summary.total - 1),
            [issue.severity]: Math.max(0, issues.summary[issue.severity] - 1)
          }
        };
      }
      await onDismiss();
    } catch (caught) {
      dismissError = asApiError(caught).message || 'Could not dismiss the issue.';
    } finally {
      dismissing = null;
      leavingIssue = null;
    }
  }
</script>

{#if error || actionableIssues.length > 0}
<div class="min-w-0 max-w-full" data-testid="dashboard-issues-strip">
  {#if error}
    <div data-testid="dashboard-issues-error">
      <Card class="border border-warning-border bg-warning-subtle p-4 text-sm text-warning">
        <p>Could not load system issues: {error}</p>
        <Button class="mt-3" size="sm" variant="secondary" onclick={onRetry}>Try again</Button>
      </Card>
    </div>
  {/if}
  {#if dismissError}
    <p class="mb-2 text-sm text-danger" role="alert">{dismissError}</p>
  {/if}
  {#if actionError}<p class="mb-2 text-sm text-danger" role="alert">{actionError}</p>{/if}
  {#if actionableIssues.length > 0}
    <div class="min-w-0 max-w-full" data-testid="dashboard-issues-needs-attention">
      <div class={`min-w-0 max-w-full border-b border-separator px-3 py-2 md:flex ${expandedIssues.length ? 'md:max-h-[60vh]' : 'md:max-h-40'} md:min-h-0 md:flex-col md:overflow-hidden`}>
        <div class="flex min-w-0 shrink-0 items-start gap-2 text-xs font-medium text-muted">
          <span class="min-w-0 break-words [overflow-wrap:anywhere]" data-testid="dashboard-issues-headline">{summary.headline}</span>
        </div>
        <ul
          class="mt-2 grid min-w-0 max-w-full gap-2 sm:grid-cols-2 md:min-h-0 md:flex-1 md:auto-rows-min md:overflow-y-auto"
          data-testid="dashboard-issues-list"
          aria-label="System issues needing attention"
        >
          {#each actionableIssues as issue (issue.id)}
            <li
              class={`dashboard-issue-row flex min-w-0 max-w-full flex-col items-stretch gap-2 rounded-xl border px-3 py-2 sm:flex-row sm:items-center sm:justify-between sm:gap-3 ${toneClasses[issue.severity] ?? toneClasses.info}`}
              data-leaving={leavingIssue === issue.id}
              data-testid={`dashboard-issue-${issue.id}`}
            >
               <div class="flex min-w-0 max-w-full flex-1 items-start gap-2">
                <span class={`h-2 w-2 shrink-0 rounded-full ${severityDot[issue.severity] ?? 'bg-muted'}`} aria-hidden="true"></span>
                <div class="min-w-0 max-w-full">
                  <p class="break-words text-sm font-medium [overflow-wrap:anywhere]">{issue.title}</p>
                  <p class="break-words text-xs opacity-80 [overflow-wrap:anywhere]">{issue.detail}</p>
                  {#if issue.resource.type === 'executor'}
                    {#if expandedIssues.includes(issue.id)}
                      <div id={`issue-details-${issue.id}`} class="mt-2">
                        <ExecutorRuntimeDiagnostics executorId={issue.resource.id} onChanged={onRetry} />
                      </div>
                    {/if}
                  {/if}
                </div>
              </div>
              <div class="flex min-w-0 flex-wrap items-center justify-end gap-2 sm:shrink-0">
                {#if issue.task_id}
                  <Button size="sm" variant="secondary" onclick={() => openTask(issue)}>Task details</Button>
                  {#if canMutate && issue.task_retry_available}
                    <Button size="sm" variant="secondary" disabled={busyAction !== null} onclick={() => void retryTask(issue)}>Retry task</Button>
                  {/if}
                {/if}
                {#if canMutate && issue.resource.type === 'llm_provider'}
                  <Button size="sm" variant="secondary" disabled={busyAction !== null} onclick={() => void refreshProvider(issue)}>Refresh status</Button>
                {/if}
                {#if issue.resource.type === 'executor'}
                  <Button size="sm" variant="ghost"
                    aria-expanded={expandedIssues.includes(issue.id)}
                    aria-controls={`issue-details-${issue.id}`}
                    onclick={() => { expandedIssues = expandedIssues.includes(issue.id)
                      ? expandedIssues.filter((id) => id !== issue.id) : [...expandedIssues, issue.id]; }}>
                    {expandedIssues.includes(issue.id) ? 'Hide details' : 'Show details'}
                  </Button>
                {/if}
                {#if issue.dismiss_token && issue.resource.type === 'schedule'}
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={dismissing === issue.id}
                    aria-label={`Dismiss ${issue.title}`}
                    data-testid={`dashboard-issue-dismiss-${issue.id}`}
                    onclick={() => void dismiss(issue)}
                  >
                    Dismiss
                  </Button>
                {/if}
                <Button size="sm" variant="secondary" data-testid={`dashboard-issue-action-${issue.id}`} onclick={() => openAction(issue)}>
                  {issue.action_label ?? 'View'}
                </Button>
              </div>
            </li>
          {/each}
        </ul>
      </div>
    </div>
  {/if}
</div>
{/if}

<style>
  @media (prefers-reduced-motion: no-preference) {
    .dashboard-issue-row {
      animation: dashboard-issue-enter 220ms cubic-bezier(0.2, 0.8, 0.2, 1);
      transition: opacity 200ms ease, transform 220ms cubic-bezier(0.2, 0.8, 0.2, 1);
    }

    .dashboard-issue-row[data-leaving='true'] {
      opacity: 0;
      transform: translateY(-8px) scale(0.97);
    }
  }

  @keyframes dashboard-issue-enter {
    from {
      opacity: 0;
      transform: translateY(-8px) scale(0.97);
    }
  }
</style>
