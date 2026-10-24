import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { get, writable } from 'svelte/store';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DashboardIssuesResponse, ProviderMonitor, Project } from '$lib/types/api';
import DashboardHealthStrip from './DashboardHealthStrip.svelte';
import { inbox } from '$lib/stores/inbox';

const { monitorList, monitor, refreshMonitor } = vi.hoisted(() => ({ monitorList: vi.fn(), monitor: vi.fn(), refreshMonitor: vi.fn() }));
vi.mock('$lib/api/client', () => ({ api: { llmProviders: { monitorList, monitor, refreshMonitor } }, asApiError: (e: unknown) => e }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/stores/auth', () => {
  const store = writable({ user: { email: 'owner@cognis.test', role: 'user' } });
  return { auth: { subscribe: store.subscribe, getSnapshot: () => get(store) } };
});

const provider: ProviderMonitor = {
  provider_id: 'claude', display_name: 'Claude', monitoring: { enabled: false, interval_minutes: 15, warning_percent: 20, critical_percent: 0 },
  health_status: 'unknown', health_detail: 'Not checked', health_checked_at: null, checked_at: null, next_refresh_at: null,
  usage: null, error: null, alert_severity: null, stale: true
};
const issues: DashboardIssuesResponse = {
  generated_at: '2026-10-01T08:00:00Z', summary: { total: 1, critical: 0, warning: 1, info: 0, truncated: false },
  issues: [{ id: 'quota', severity: 'warning', kind: 'provider_quota', title: 'Low quota', detail: '15% left',
    resource: { type: 'llm_provider', id: 'claude', label: 'Claude' }, observed_at: null,
    action_url: '/settings?tab=providers', action_label: 'Provider' }]
};
const props = { onRetry: vi.fn(), onDismiss: vi.fn() };
const projects: Project[] = [{
  project_id: 'proj_home', name: 'Home', metadata: { icon: 'house' }, color: '#fbbf24', avatar_url: null,
  owner_email: 'owner@cognis.test', description: null, instructions: null, default_workflow_id: null,
  avatar_image_id: null, status: 'active', sources: [], workflow_ids: [], active_schedule_count: 0, grants: [],
  is_shared_with_me: false, shared_by_email: null, granted_permission: null, is_readonly_for_caller: false,
  created_at: null, updated_at: null,
}];

describe('compact dashboard health strip', () => {
  beforeEach(() => {
    window.localStorage.clear();
    inbox.set({ items: [], unreadCount: 0, loading: false, error: null, cursor: null, unreadOnly: false, initialized: false });
    monitorList.mockReset(); monitor.mockReset(); refreshMonitor.mockReset(); monitorList.mockResolvedValue([provider]);
  });
  it('includes personal unread entries in the existing Notifications tab', async () => {
    inbox.set({
      items: [{ notification_id: 'inbox-share', kind: 'sharing.agent.shared', title: 'Agent shared with you', body: 'Owner shared an agent.', href: '/agents/shared', created_at: '2026-10-01T08:00:00Z', read_at: null }],
      unreadCount: 1, loading: false, error: null, cursor: null, unreadOnly: false, initialized: true,
    });
    render(DashboardHealthStrip, { ...props, issues });
    expect(await screen.findByRole('tab', { name: /Notifications.*2/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('Low quota')).toBeInTheDocument();
    expect(screen.getByText('Agent shared with you')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View all' })).toHaveAttribute('href', '/notifications');
  });
  it('defaults to projects without notifications, preserving order and links', async () => {
    render(DashboardHealthStrip, { ...props, issues: null, projects });
    expect(await screen.findByRole('tab', { name: /Projects/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('link', { name: /Home/ })).toHaveAttribute('href', '/projects/proj_home');
    expect(screen.getByTestId('dashboard-project-strip')).toHaveClass('overflow-x-auto');
  });
  it('places Projects between notifications and providers and remembers explicit selection', async () => {
    const first = render(DashboardHealthStrip, { ...props, issues, projects });
    await screen.findByRole('tab', { name: /Providers/ });
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent?.trim())).toEqual(['Notifications 1', 'Projects 1', 'Providers 1']);
    await fireEvent.click(screen.getByRole('tab', { name: /Projects/ }));
    first.unmount();
    render(DashboardHealthStrip, { ...props, issues, projects });
    expect(await screen.findByRole('tab', { name: /Projects/ })).toHaveAttribute('aria-selected', 'true');
  });
  it('falls back when the saved projects tab has no projects', async () => {
    window.localStorage.setItem('cognis.dashboardHealth.selected', 'projects');
    render(DashboardHealthStrip, { ...props, issues });
    expect(screen.queryByRole('tab', { name: /Projects/ })).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Notifications/ })).toHaveAttribute('aria-selected', 'true');
  });
  it('remembers a click on the already active default tab when notifications arrive', async () => {
    const view = render(DashboardHealthStrip, { ...props, issues: null, projects });
    await fireEvent.click(screen.getByRole('tab', { name: /Projects/ }));
    await view.rerender({ issues });
    expect(screen.getByRole('tab', { name: /Projects/ })).toHaveAttribute('aria-selected', 'true');
    expect(window.localStorage.getItem('cognis.dashboardHealth.selected')).toBe('projects');
  });
  it('keeps a single provider tab and refresh icon available', async () => {
    render(DashboardHealthStrip, { ...props, issues: null });
    expect(await screen.findByText('Claude')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Providers/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('auto off')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Provider health: unknown' })).toBeInTheDocument();
    expect(screen.queryByText('Usage unknown')).not.toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    refreshMonitor.mockResolvedValue(provider);
    await fireEvent.click(screen.getByRole('button', { name: 'Refresh Claude' }));
    await waitFor(() => expect(refreshMonitor).toHaveBeenCalledWith('claude'));
    expect(monitor).not.toHaveBeenCalled();
  });
  it('defaults to Notifications and switches to Providers', async () => {
    render(DashboardHealthStrip, { ...props, issues });
    expect(await screen.findByRole('tab', { name: /Providers/ })).toHaveAttribute('aria-selected', 'false');
    expect(screen.getByRole('tab', { name: /Notifications/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('Low quota')).toBeInTheDocument();
    await fireEvent.click(screen.getByRole('tab', { name: /Providers/ }));
    expect(screen.getByText('Claude')).toBeInTheDocument();
  });
  it('omits the whole row when no notifications or providers exist', async () => {
    monitorList.mockResolvedValue([]);
    render(DashboardHealthStrip, { ...props, issues: null });
    await waitFor(() => expect(monitorList).toHaveBeenCalledOnce());
    expect(screen.queryByTestId('dashboard-health-strip')).not.toBeInTheDocument();
  });
  it('collapses only the content, preserves counts, and opens the selected tab', async () => {
    render(DashboardHealthStrip, { ...props, issues });
    const providers = await screen.findByRole('tab', { name: /Providers.*1/ });
    await fireEvent.click(screen.getByRole('button', { name: 'Collapse dashboard status' }));
    expect(screen.getByText('Low quota')).not.toBeVisible();
    expect(screen.getByRole('tab', { name: /Notifications.*1/ })).toBeVisible();
    expect(providers).toBeVisible();
    expect(screen.getByRole('button', { name: 'Expand dashboard status' })).toHaveAttribute('aria-expanded', 'false');
    expect(window.localStorage.getItem('cognis.dashboardHealth.collapsed')).toBe('true');
    await fireEvent.click(providers);
    expect(screen.getByText('Claude')).toBeVisible();
    expect(providers).toHaveAttribute('aria-selected', 'true');
    expect(window.localStorage.getItem('cognis.dashboardHealth.collapsed')).toBe('false');
  });
  it('restores collapse after remount and reopens the current single tab', async () => {
    const first = render(DashboardHealthStrip, { ...props, issues: null });
    await screen.findByText('Claude');
    await fireEvent.click(screen.getByRole('button', { name: 'Collapse dashboard status' }));
    first.unmount();
    render(DashboardHealthStrip, { ...props, issues: null });
    const tab = await screen.findByRole('tab', { name: /Providers/ });
    expect(screen.getByText('Claude')).not.toBeVisible();
    await fireEvent.click(tab);
    expect(screen.getByText('Claude')).toBeVisible();
    await fireEvent.click(tab);
    expect(screen.getByText('Claude')).not.toBeVisible();
    await fireEvent.click(tab);
    expect(screen.getByText('Claude')).toBeVisible();
    await fireEvent.click(screen.getByRole('button', { name: 'Collapse dashboard status' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Expand dashboard status' }));
    expect(screen.getByText('Claude')).toBeVisible();
  });
  it('does not collapse on arrow-key selection of the current tab', async () => {
    render(DashboardHealthStrip, { ...props, issues: null });
    const tab = await screen.findByRole('tab', { name: /Providers/ });
    await fireEvent.keyDown(tab, { key: 'ArrowRight' });
    expect(screen.getByText('Claude')).toBeVisible();
  });
});
