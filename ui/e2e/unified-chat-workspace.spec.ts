import { expect, test, type Page } from '@playwright/test';

async function mockWorkspace(page: Page): Promise<string[]> {
  const backfills: string[] = [];
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url());
    const stepId = url.pathname.match(/task-steps\/([^/]+)/)?.[1]
      ?? url.pathname.match(/step-runs\/([^/]+)/)?.[1];
    const sessionId = url.pathname.match(/sessions\/([^/]+)/)?.[1];
    const conversationId = url.pathname.match(/conversations\/([^/]+)/)?.[1]
      ?? `acceptance-conversation-${stepId?.split('-').pop() ?? 3}`;
    const selectedId = stepId ?? sessionId ?? conversationId;
    const scope = stepId
      ? { kind: 'task_step', key: `task_step:${stepId}`, step_run_id: stepId, task_id: 'acceptance-task', conversation_id: conversationId }
      : sessionId
        ? { kind: 'session', key: `session:${sessionId}`, session_id: sessionId, conversation_id: 'acceptance-conversation-3' }
        : { kind: 'conversation', key: `conversation:${conversationId}`, conversation_id: conversationId };
    const root = {
      key: 'acceptance-root', root_key: 'acceptance-root', kind: 'root', edge_kind: 'root', ordinal: 0,
      session_id: sessionId ?? `acceptance-session-${stepId?.split('-').pop() ?? 3}`, conversation_id: conversationId,
      event_store_session_id: 'acceptance-session-3', title: 'Execute maintenance', agent_id: 'acceptance-agent',
      status: 'active', current: true, superseded: false,
      backing_session_ids: [sessionId ?? `acceptance-session-${stepId?.split('-').pop() ?? 3}`],
    };
    const child = {
      ...root, key: 'acceptance-child', parent_key: root.key, kind: 'delegate', session_id: 'sess_acceptance_child',
      event_store_session_id: 'sess_acceptance_child', title: 'Inspect service health', status: 'completed',
    };
    const managed = {
      ...child, key: 'acceptance-managed', kind: 'managed', conversation_id: 'acceptance-managed-conversation',
      session_id: 'sess_acceptance_managed', event_store_session_id: 'sess_acceptance_managed',
      title: 'Review service health', backing_session_ids: ['sess_acceptance_managed'],
    };
    const conversation = { conversation_id: conversationId, agent_id: 'acceptance-agent', title: 'Maintenance acceptance', active_session_id: root.session_id, status: 'active',
      ...(conversationId === managed.conversation_id ? { managed_agent: { conversation_state: 'open', turn_state: 'idle' }, has_active_turn: false } : {}) };
    const message = (index: number) => ({
      id: `message:${selectedId}:${index}`, message_id: `${selectedId}:${index}`, kind: 'message', role: 'assistant',
      sort_key: `0000:${String(index).padStart(15, '0')}:000000:02:000000000`,
      source_refs: [], stable: true, partial: false, attachments: [],
      content: `### ${selectedId} · progress ${index}\n\nVerified service health. No changes applied.\n\n\`verification --read-only\``,
    });
    let body: unknown = {};
    if (url.pathname.endsWith('/auth/me')) body = { email: 'workspace-acceptance@cognis.test', role: 'user' };
    else if (url.pathname.endsWith('/snapshot')) body = {
      schema_version: 2, projection_version: 'acceptance', scope, conversation,
      timeline: { items: Array.from({ length: 20 }, (_, index) => message(index + 20)), has_more_before: true, before_cursor: 'older-1' },
      state: { state_version: 1, active_turn: {}, pending: {}, capabilities: [], active_session: { session_id: root.session_id, status: 'active' } },
      queue: { messages: [], queued_count: 0 }, runtime: null, cursor: `cursor:${selectedId}`, server_time: '',
    };
    else if (url.pathname.endsWith('/sync')) body = {
      schema_version: 2, projection_version: 'acceptance', scope, conversation_id: conversationId,
      cursor_before: `cursor:${selectedId}`, cursor_after: `cursor:${selectedId}`, ops: [], has_more: false, reset_required: false, runtime: null, server_time: '',
    };
    else if (url.pathname.endsWith('/timeline')) {
      const before = url.searchParams.get('before');
      backfills.push(before ?? '');
      body = {
        schema_version: 2, projection_version: 'acceptance', scope, conversation_id: conversationId,
        items: before === 'older-1' ? [] : Array.from({ length: 20 }, (_, index) => message(index)),
        before_cursor: before === 'older-1' ? 'older-2' : null,
        has_more_before: before === 'older-1', server_time: '',
      };
    } else if (url.pathname.endsWith('/activity-overview')) body = {
      schema_version: 2, projection_version: 'acceptance', scope, root_key: root.key,
      workstreams: [root, child, managed], summary: { mutations: 0, commands: 0, changed_files: 0, artifacts: 0 }, recent: {}, graph_fingerprint: 'acceptance', graph_truncated: false,
      materialization: { state: 'live', lag_count: 0, failure_count: 0 },
    };
    else if (url.pathname.endsWith('/work')) body = {
      schema_version: 2, projection_version: 'acceptance', scope, workstreams: [root, child],
      mutations: [], commands: [], artifacts: [], deliverables: [],
      summary: { mutations: 0, commands: 0, changed_files: 0, artifacts: 0 },
      materialization: { state: 'live', lag_count: 0, failure_count: 0 },
      has_more_before: false, before_cursor: null, server_time: '',
    };
    else if (/\/step-runs\/[^/]+$/.test(url.pathname)) {
      const attempt = Number(stepId?.split('-').pop());
      body = { step_run_id: stepId, task_id: 'acceptance-task', step_name: 'execute',
        conversation_id: `acceptance-conversation-${attempt}`, session_id: `acceptance-session-${attempt}`,
        status: attempt === 3 ? 'running' : 'failed', attempt, attempt_number: attempt, todos: [] };
    }
    else if (/\/conversations\/[^/]+$/.test(url.pathname)) body = conversation;
    else if (['/sessions', '/models', '/interactions', '/todos', '/notifications'].some(suffix => url.pathname.endsWith(suffix))) body = [];
    await route.fulfill({ json: body });
  });
  return backfills;
}

test('task, dashboard and pinned hosts share history, child navigation and inspector behavior', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => { errors.push(error.message); console.error(error.message); });
  const backfills = await mockWorkspace(page);
  for (const surface of ['task', 'dashboard', 'pinned']) {
    await page.goto(`/?surface=${surface}`);
    if (surface === 'task') await page.getByRole('button', { name: 'Open step logs' }).click();
    const viewport = page.getByTestId('scoped-timeline-viewport');
    await expect(viewport).toBeVisible();
    await expect(page.getByText(/progress 39/).first()).toBeVisible();
    // A real trusted keyboard scroll, with no wheel event to restart pagination.
    await viewport.focus();
    await page.keyboard.press('Control+Home');
    await expect.poll(() => backfills.length).toBeGreaterThanOrEqual(2);
    await expect(page.getByText(/progress 0$/).first()).toBeVisible();
    if (surface === 'task') {
      await page.getByRole('combobox', { name: 'Step attempt' }).selectOption('acceptance-step-1');
      await expect(page.locator('[data-scope-key="task_step:acceptance-step-1"]')).toBeVisible();
      await expect(page.getByTestId('session-activity-status')).toContainText('Attempt 1');
      await page.getByRole('combobox', { name: 'Step attempt' }).selectOption('acceptance-step-3');
      await page.getByTestId('session-logs-header-info').click();
    } else {
      if (surface === 'pinned') await page.getByRole('button', { name: 'Toggle session details' }).click();
    }
    await expect(page.getByRole('tab', { name: 'Work', exact: true })).toBeVisible();
    await page.getByRole('tab', { name: 'Work', exact: true }).click();
    await page.getByRole('tab', { name: 'Overview', exact: true }).click();
    const expand = page.getByRole('button', { name: 'Expand Execute maintenance', exact: true });
    if (await expand.count()) await expand.click();
    await expect(page.getByRole('button', { name: 'View session Inspect service health', exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`${surface}-workspace.png`), fullPage: true });
    await page.getByRole('button', { name: 'View session Inspect service health', exact: true }).click();
    await expect(page.locator('[data-scope-key="session:sess_acceptance_child"]')).toBeVisible();
    await page.getByRole('link', { name: 'Back to parent conversation', exact: true }).click();
    if (await expand.count()) await expand.click();
    await page.getByRole('button', { name: 'View session Review service health', exact: true }).click();
    await expect(page.locator('[data-scope-key="conversation:acceptance-managed-conversation"]')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Continue', exact: true })).toBeEnabled();
    await page.getByRole('link', { name: 'Back to parent conversation', exact: true }).click();
    backfills.length = 0;
  }
  expect(errors).toEqual([]);
});

for (const viewport of [{ width: 393, height: 852 }, { width: 1440, height: 1000 }]) {
  test(`compact task and child headers at ${viewport.width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await mockWorkspace(page);
    await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' });
    await page.goto('/?surface=task&attempts=5&status=failed');
    await page.getByRole('button', { name: 'Open step logs' }).click();
    const taskHeader = page.getByTestId('session-logs-header');
    const picker = taskHeader.getByRole('combobox', { name: 'Step attempt' });
    await expect(picker).toHaveValue('acceptance-step-5');
    await expect(picker.locator('option:checked')).toHaveText('Attempt 5 of 5 · failed');
    await expect(page.getByText('Step history', { exact: true })).toHaveCount(0);
    await expect(page.getByTestId('scoped-timeline-status-row')).toHaveCount(0);
    await expect(taskHeader.locator('svg.lucide-info')).toHaveCount(1);
    const taskSizes = await taskHeader.getByRole('button').evaluateAll(buttons =>
      buttons.map(button => ({ width: button.getBoundingClientRect().width, height: button.getBoundingClientRect().height })));
    expect(taskSizes).toHaveLength(3);
    expect(new Set(taskSizes.map(size => `${size.width}x${size.height}`)).size).toBe(1);
    const taskBounds = (await taskHeader.boundingBox())!;
    const pickerBounds = (await picker.boundingBox())!;
    expect(taskBounds.height).toBeLessThanOrEqual(72);
    expect(pickerBounds.y).toBeGreaterThanOrEqual(taskBounds.y);
    const pickerLayout = await picker.evaluate(element => ({
      classes: element.className,
      position: getComputedStyle(element).position, top: getComputedStyle(element).top,
      parentClasses: element.parentElement?.className,
      parentPosition: getComputedStyle(element.parentElement!).position,
    }));
    expect(pickerBounds.y + pickerBounds.height, JSON.stringify(pickerLayout))
      .toBeLessThanOrEqual(taskBounds.y + taskBounds.height);
    await picker.selectOption('acceptance-step-1');
    await expect(picker.locator('option:checked')).toHaveText('Attempt 1 of 5 · failed');
    await picker.selectOption('acceptance-step-5');
    await expect(page.getByText('acceptance-step-5 · progress 39', { exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`task-header-${viewport.width}.png`) });
    await page.goto('/?surface=child');
    const childHeader = page.getByTestId('child-header');
    await expect(childHeader.getByRole('link', { name: 'Back to parent conversation' })).toHaveText('');
    await expect(childHeader).not.toContainText('Following');
    await expect(childHeader.locator('svg.lucide-info')).toHaveCount(1);
    await expect(page.getByTestId('scoped-timeline-status-row')).toHaveCount(0);
    const childSizes = await childHeader.getByRole('button').evaluateAll(buttons =>
      buttons.map(button => ({ width: button.getBoundingClientRect().width, height: button.getBoundingClientRect().height })));
    expect(childSizes).toEqual(taskSizes);
    expect((await childHeader.boundingBox())!.height).toBeLessThanOrEqual(72);
    const info = childHeader.getByRole('button', { name: 'Toggle session details' });
    await info.click();
    await expect(info).toHaveAttribute('aria-expanded', 'true');
    const timeline = page.getByTestId('scoped-timeline-viewport');
    await expect(timeline).toBeVisible();
    await timeline.evaluate(element => { element.scrollTop = element.scrollHeight; });
    const indicator = page.getByTestId('timeline-running-indicator');
    await expect(indicator).toBeVisible();
    await expect(indicator).toHaveText('');
    await expect(indicator.locator('.animate-bounce')).toHaveCount(3);
    await expect(page.getByRole('navigation', { name: 'Live tail controls' })).toHaveCount(0);
    const widths = await childHeader.evaluate(element => ({ client: element.clientWidth, scroll: element.scrollWidth }));
    expect(widths.scroll).toBeLessThanOrEqual(widths.client);
    await page.screenshot({ path: testInfo.outputPath(`child-header-${viewport.width}.png`) });
    expect(errors).toEqual([]);
  });
}
