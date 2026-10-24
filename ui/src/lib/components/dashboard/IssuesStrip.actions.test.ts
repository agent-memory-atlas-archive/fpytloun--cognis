import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DashboardIssue, DashboardIssuesResponse } from '$lib/types/api';
import IssuesStrip from './IssuesStrip.svelte';

const mocks = vi.hoisted(() => ({
  goto: vi.fn(), rerun: vi.fn(), confirm: vi.fn(), refresh: vi.fn(),
  role: 'user',
  auth: { subscribe: (fn: (value: unknown) => void) => {
    fn({ user: { role: mocks.role, email: 'owner@cognis.test' } }); return () => {};
  } },
}));
vi.mock('$app/navigation', () => ({ goto: mocks.goto }));
vi.mock('$lib/api/client', () => ({
  api: { tasks: { rerun: mocks.rerun }, llmProviders: { refreshMonitor: mocks.refresh } },
  asApiError: (error: Error) => error,
}));
vi.mock('$lib/stores/confirm', () => ({ confirmAction: mocks.confirm }));
vi.mock('$lib/stores/auth', () => ({ auth: mocks.auth }));
vi.mock('$lib/provider-monitor', () => ({ loadProviderMonitor: mocks.refresh }));

const issue: DashboardIssue = {
  id: 'schedule-failure', severity: 'warning', kind: 'schedule_failed', title: 'Curation failed',
  detail: '1 consecutive failure.', resource: { type: 'schedule', id: 'schedule-curation', label: 'Curation' },
  observed_at: null, action_url: '/schedules/schedule-curation', action_label: 'View schedule',
  task_id: 'task-curation', task_retry_available: true,
};
function renderIssue(value = issue, onDismiss = vi.fn()) {
  return render(IssuesStrip, { onDismiss, issues: {
    issues: [value], generated_at: '2026-10-01T00:00:00Z',
    summary: { total: 1, warning: 1, critical: 0, info: 0, truncated: false },
  } satisfies DashboardIssuesResponse });
}
afterEach(cleanup);
beforeEach(() => { vi.clearAllMocks(); mocks.role = 'user'; mocks.confirm.mockResolvedValue(true); mocks.rerun.mockResolvedValue({ task_id: 'task-retry', created_new: true }); });
describe('notification actions', () => {
  it('opens the failed task directly while retaining its schedule link', async () => {
    renderIssue();
    await fireEvent.click(screen.getByRole('button', { name: 'Task details' }));
    expect(mocks.goto).toHaveBeenCalledWith('/tasks/task-curation');
    await fireEvent.click(screen.getByRole('button', { name: 'View schedule' }));
    expect(mocks.goto).toHaveBeenCalledWith('/schedules/schedule-curation');
  });
  it('confirms a fresh retry and navigates to the newly created task', async () => {
    renderIssue();
    await fireEvent.click(screen.getByRole('button', { name: 'Retry task' }));
    await vi.waitFor(() => expect(mocks.goto).toHaveBeenCalledWith('/tasks/task-retry'));
    expect(mocks.rerun).toHaveBeenCalledExactlyOnceWith('task-curation');
    expect(mocks.confirm).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('may execute again') }));
  });
  it('does not execute a declined retry', async () => {
    mocks.confirm.mockResolvedValue(false);
    renderIssue();
    await fireEvent.click(screen.getByRole('button', { name: 'Retry task' }));
    await vi.waitFor(() => expect(mocks.confirm).toHaveBeenCalledOnce());
    expect(mocks.rerun).not.toHaveBeenCalled();
  });
  it('does not offer retry for a nonfailed task', () => {
    renderIssue({ ...issue, task_retry_available: false });
    expect(screen.queryByRole('button', { name: 'Retry task' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Task details' })).toBeInTheDocument();
  });
  it('keeps navigation but hides mutations for viewers', () => {
    mocks.role = 'viewer';
    renderIssue();
    expect(screen.getByRole('button', { name: 'Task details' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry task' })).not.toBeInTheDocument();
  });
  it('coalesces clicks while the retry confirmation is pending', async () => {
    let resolve!: (value: boolean) => void;
    mocks.confirm.mockReturnValue(new Promise<boolean>((done) => { resolve = done; }));
    renderIssue();
    const button = screen.getByRole('button', { name: 'Retry task' });
    await fireEvent.click(button);
    await fireEvent.click(button);
    expect(mocks.confirm).toHaveBeenCalledOnce();
    resolve(true);
    await vi.waitFor(() => expect(mocks.rerun).toHaveBeenCalledOnce());
  });
  it('shows mutation errors without dismissing the failure', async () => {
    mocks.rerun.mockRejectedValue(new Error('Task no longer available'));
    renderIssue();
    await fireEvent.click(screen.getByRole('button', { name: 'Retry task' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Task no longer available');
    expect(screen.getByText('Curation failed')).toBeInTheDocument();
  });
  it('refreshes provider health using the existing no-inference monitor', async () => {
    const onDismiss = vi.fn();
    mocks.refresh.mockResolvedValue({ provider_id: 'codex' });
    renderIssue({ ...issue, resource: { type: 'llm_provider', id: 'codex', label: 'Codex' }, task_id: null }, onDismiss);
    await fireEvent.click(screen.getByRole('button', { name: 'Refresh status' }));
    await vi.waitFor(() => expect(onDismiss).toHaveBeenCalledOnce());
    expect(mocks.refresh).toHaveBeenCalledExactlyOnceWith('codex', true);
  });
});
