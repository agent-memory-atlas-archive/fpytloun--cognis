import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';
import { api } from '$lib/api/client';
import type { Agent, Schedule } from '$lib/types/api';
import SchedulesWorkspace from './SchedulesWorkspace.svelte';
import ScheduleDetailWorkspace from './ScheduleDetailWorkspace.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/stores', () => ({ page: writable({ url: new URL('http://localhost/schedules') }) }));
vi.mock('$lib/stores/auth', () => ({
  auth: writable({ user: { role: 'user', email: 'owner@cognis.local' } })
}));
vi.mock('$lib/stores/toasts', () => ({ addToast: vi.fn() }));

const schedule = {
  schedule_id: 'daily-review', name: 'Daily review', schedule_type: 'cron',
  cron_expr: '0 9 * * *', timezone: 'UTC', agent_id: 'reviewer',
  agent_profile_id: 'careful', enabled: true, task_template: {},
  human_schedule: 'Every day at 09:00', consecutive_errors: 0,
  completion_mode_family: 'default', allow_silent_completion: false,
  max_concurrent_runs: 1, retry_failed_tasks: false, fail_paused_task_on_next_fire: true
} as Schedule;

function pending<T>(): Promise<T> { return new Promise(() => {}); }

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api.schedules, 'list').mockResolvedValue([schedule]);
  vi.spyOn(api.schedules, 'detail').mockResolvedValue(schedule);
  vi.spyOn(api.schedules, 'runs').mockResolvedValue([]);
  vi.spyOn(api.agents, 'listAll').mockResolvedValue([]);
  vi.spyOn(api.projects, 'list').mockResolvedValue([]);
  vi.spyOn(api.skills, 'list').mockResolvedValue([]);
  vi.spyOn(api.workflows, 'listAll').mockResolvedValue([]);
  vi.spyOn(api.conversations, 'listAll').mockResolvedValue([]);
});
afterEach(cleanup);

describe('schedule loading boundaries', () => {
  it('renders schedules while labels are pending, without loading create-only registries', async () => {
    vi.mocked(api.agents.listAll).mockReturnValue(pending<Agent[]>());
    vi.mocked(api.projects.list).mockReturnValue(pending());
    render(SchedulesWorkspace);
    expect(await screen.findByText('Daily review')).toBeVisible();
    expect(api.schedules.list).toHaveBeenCalledTimes(1);
    expect(api.skills.list).not.toHaveBeenCalled();
    expect(api.workflows.listAll).not.toHaveBeenCalled();
    expect(api.conversations.listAll).not.toHaveBeenCalled();
  });

  it('loads create choices on demand and conversation history only for targeted delivery', async () => {
    render(SchedulesWorkspace);
    await fireEvent.click(await screen.findByRole('button', { name: 'New schedule' }));
    await waitFor(() => expect(api.workflows.listAll).toHaveBeenCalledTimes(1));
    expect(api.skills.list).toHaveBeenCalledTimes(1);
    expect(api.conversations.listAll).not.toHaveBeenCalled();
    const delivery = screen.getByDisplayValue('Preferred channel');
    await fireEvent.change(delivery, { target: { value: 'specific_conversation' } });
    await waitFor(() => expect(api.conversations.listAll).toHaveBeenCalledTimes(1));
  });

  it('keeps schedules visible after a label registry fails and refresh does not reload registries', async () => {
    vi.mocked(api.agents.listAll).mockRejectedValue(new Error('Agent registry unavailable'));
    const view = render(SchedulesWorkspace);
    expect(await screen.findByText('Daily review')).toBeVisible();
    await view.rerender({ projectId: 'engineering' });
    await waitFor(() => expect(api.schedules.list).toHaveBeenCalledWith({ project_id: 'engineering' }));
    expect(api.agents.listAll).toHaveBeenCalledTimes(1);
  });

  it('renders schedule status before configuration choices or runs and preserves the profile', async () => {
    let resolveAgents!: (items: Agent[]) => void;
    vi.mocked(api.agents.listAll).mockReturnValue(new Promise((resolve) => { resolveAgents = resolve; }));
    vi.mocked(api.schedules.runs).mockReturnValue(pending());
    render(ScheduleDetailWorkspace, { id: schedule.schedule_id });
    expect(await screen.findByRole('heading', { name: 'Daily review' })).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Save changes' })).not.toBeInTheDocument();
    expect(api.conversations.listAll).not.toHaveBeenCalled();
    resolveAgents([{
      agent_id: 'reviewer', name: 'Reviewer', agent_profiles: { careful: {} }
    } as unknown as Agent]);
    await screen.findByRole('button', { name: 'Save changes' });
    expect(screen.getByDisplayValue('careful')).toBeInTheDocument();
    expect(api.workflows.listAll).toHaveBeenCalledTimes(1);
  });
});
