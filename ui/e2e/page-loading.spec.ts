import { expect, test, type Page } from '@playwright/test';
import { syncHealthWorkflow } from '../src/lib/testing/workflow-plan-fixture';

test.use({ serviceWorkers: 'block', bypassCSP: process.env.COGNIS_E2E_STATIC_PREVIEW === '1' });

async function fixture(page: Page, blocked: string[] = []) {
  const requests: string[] = [];
  const errors: string[] = [];
  const saves: Record<string, unknown>[] = [];
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const task = {
    task_id: 'loading-review', title: 'Review loading boundaries', description: 'Check primary data',
    expected_output: null, priority: 0, status: 'draft', agent_id: 'reviewer',
    agent_profile_id: 'careful', project_id: null, workflow_id: null, skill_id: null,
    source_type: 'manual', source_ref: null, created_by: 'owner@cognis.local',
    delivery: { mode: 'preferred_channel', target: null }, completion_mode_family: 'default',
    allow_silent_completion: false, interaction_mode_override: null, session_policy: {},
    dependencies: [], step_runs: [], workflow_run: null, workflow_state: null, pending_pause: null,
    result_data: null, created_at: null, updated_at: null
  };
  const schedule = {
    schedule_id: 'daily-review', name: 'Daily review', description: '', schedule_type: 'cron',
    cron_expr: '0 9 * * *', timezone: 'UTC', agent_id: 'reviewer', enabled: true,
    task_template: {}, human_schedule: 'Every day at 09:00', consecutive_errors: 0,
    completion_mode_family: 'default', allow_silent_completion: false, max_concurrent_runs: 1,
    retry_failed_tasks: false, fail_paused_task_on_next_fire: true
  };
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    requests.push(path);
    if (blocked.includes(path)) await gate;
    let body: unknown = [];
    if (path === '/api/auth/me') body = { email: 'owner@cognis.local', name: 'Owner', role: 'user' };
    else if (path === '/api/health') body = { status: 'ok', services: {}, llm_available: true };
    else if (path === '/api/bootstrap-status') body = { has_users: true, needs_bootstrap: false };
    else if (path === '/api/v1/dashboard/navigation-summary') body = {
      chat_groups: [], dashboard: { total: 0, critical: 0, warning: 0 }, schedules: 1, tasks: 1
    };
    else if (path.endsWith('/sidebar')) body = {
      agents: [], agent_direct_chats: [], context_types: ['web'],
      conversations: { items: [], next_cursor: null, has_more: false },
      background_work: { items: [], truncated: false }
    };
    else if (path === '/api/v1/schedules') body = [schedule];
    else if (path === '/api/v1/schedules/daily-review') body = schedule;
    else if (path === '/api/v1/tasks/board') body = { columns: Object.fromEntries(
      ['draft', 'queued', 'running', 'paused', 'done'].map((id) => [id, {
        items: id === 'draft' ? [task] : [], groups: [], cursor: null, has_more: false,
        total_count: id === 'draft' ? 1 : 0
      }])
    ) };
    else if (path === '/api/v1/tasks/loading-review/summary') body = task;
    else if (path === '/api/v1/tasks/loading-review') {
      if (route.request().method() === 'PATCH') saves.push(route.request().postDataJSON());
      body = task;
    } else if (path === '/api/v1/workflows') body = { items: [syncHealthWorkflow()], cursor: null, has_more: false };
    else if (path === '/api/v1/agents') {
      // Deliberate registry failure: an unrelated task edit must retain its profile.
      return route.fulfill({ status: 503, json: { detail: 'Agent registry unavailable' } });
    } else if (path === '/api/v1/tasks' || path.includes('/steps/') || path === '/api/v1/conversations'
      || path === '/api/v1/llm-providers') body = { items: [], cursor: null, next_cursor: null, has_more: false };
    await route.fulfill({ json: body });
  });
  await page.routeWebSocket('**/api/ws', (ws) => ws.send(JSON.stringify({ type: 'authenticated' })));
  return { requests, errors, saves, release };
}

for (const width of [390, 1440]) {
  test(`schedules render without metadata or conversation history at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const f = await fixture(page, ['/api/v1/agents', '/api/v1/projects']);
    try {
      await page.goto('/schedules');
      await expect(page.getByText('Daily review', { exact: true })).toBeVisible();
      expect(f.requests.filter((path) => path === '/api/v1/schedules')).toHaveLength(1);
      expect(f.requests).not.toContain('/api/v1/conversations');
      expect(f.requests).not.toContain('/api/v1/skills');
      expect(f.errors).toEqual([]);
    } finally { f.release(); }
  });
}

test('task board renders while filter registries are pending', async ({ page }) => {
  const f = await fixture(page, ['/api/v1/agents', '/api/v1/projects', '/api/v1/skills', '/api/v1/workflows']);
  try {
    await page.goto('/tasks');
    await expect(page.getByText('Review loading boundaries', { exact: true }).first()).toBeVisible();
    expect(f.errors).toEqual([]);
  } finally { f.release(); }
});

test('workflow registry renders before profile metadata', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const f = await fixture(page, ['/api/v1/workflows/step-profiles']);
  try {
    await page.goto('/workflows');
    await expect(page.getByTestId('workflow-registry').getByRole('button', {
      name: new RegExp(syncHealthWorkflow().name)
    })).toBeVisible();
    await expect(page.getByText('Loading workflow profiles', { exact: true })).toBeVisible();
    await expect(page.getByPlaceholder('wf_review_loop')).toHaveCount(0);
    expect(f.errors).toEqual([]);
  } finally { f.release(); }
});

test('task detail renders before choices and retains a saved profile after registry failure', async ({ page }) => {
  const f = await fixture(page, ['/api/v1/projects']);
  try {
    await page.goto('/tasks/loading-review');
    await expect(page.getByRole('heading', { name: 'Review loading boundaries', exact: true }).first()).toBeVisible();
    await page.getByRole('button', { name: 'Configure', exact: true }).click();
    await expect(page.getByText('Loading configuration choices', { exact: true })).toBeVisible();
    f.release();
    const dialog = page.getByRole('dialog', { name: 'Review loading boundaries', exact: true });
    await expect(dialog.getByRole('combobox', { name: /^Agent profile/ })).toHaveValue('careful');
    await dialog.getByLabel('Title', { exact: true }).fill('Updated loading review');
    await dialog.getByRole('button', { name: 'Save task', exact: true }).click();
    await expect.poll(() => f.saves.length).toBe(1);
    expect(f.saves[0].agent_profile_id).toBe('careful');
    expect(f.errors).toEqual([]);
  } finally { f.release(); }
});
