import { expect, test, type Page } from '@playwright/test';

test.use({ serviceWorkers: 'block', bypassCSP: true });

async function mockSettings(page: Page) {
  const requests: string[] = [];
  const errors: string[] = [];
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.continue();
    requests.push(path);
    if (['/api/v1/system/diagnostics', '/api/v1/local-models/deployments'].includes(path)) await gate;
    let body: unknown = [];
    if (path === '/api/auth/me') body = { email: 'owner@cognis.local', name: 'Owner', role: 'admin' };
    else if (path === '/api/auth/mfa') body = { enabled: false, policy: 'optional', recovery_codes_remaining: 0 };
    else if (path === '/api/health') body = { status: 'ok', services: {}, providers: {}, llm_available: true };
    else if (path === '/api/bootstrap-status') body = { has_users: true, needs_bootstrap: false };
    else if (path === '/api/v1/videos/policy') body = {
      enabled: false, per_job_usd: 5, daily_usd: 20, max_active_jobs: 2,
      max_output_bytes: 1000000, model_max_cost_usd: {}
    };
    else if (path === '/api/v1/model-routing') body = Object.fromEntries(
      ['default', 'classifier', 'compaction', 'evaluator', 'speech_to_text', 'text_to_speech',
       'image_generation', 'video_generation', 'video_editing', 'video_analysis', 'attachment_analysis',
       'embedding', 'companion_lite', 'companion_smart', 'companion_embedding'].map(
         (key) => [key, { model: null, reasoning_effort: null }]
       )
    );
    else if (path === '/api/v1/dashboard/navigation-summary') body = {
      chat_groups: [], dashboard: { total: 0, critical: 0, warning: 0 }, schedules: 0, tasks: 0
    };
    else if (path.endsWith('/sidebar')) body = {
      agents: [], agent_direct_chats: [], context_types: ['web'],
      conversations: { items: [], next_cursor: null, has_more: false },
      background_work: { items: [], truncated: false }
    };
    else if (path === '/api/v1/llm-providers' || path === '/api/v1/agents') body = {
      items: [], cursor: null, has_more: false
    };
    else if (path === '/api/v1/tasks/board') body = { columns: Object.fromEntries(
      ['draft', 'queued', 'running', 'paused', 'done'].map((column) => [
        column, { items: [], groups: [], cursor: null, has_more: false, total_count: 0 }
      ])
    ) };
    await route.fulfill({ json: body });
  });
  await page.routeWebSocket('**/api/ws', (ws) => ws.send(JSON.stringify({ type: 'authenticated' })));
  return { requests, errors, release };
}

for (const width of [390, 1440]) {
  test(`Video spending is optional account detail, not routing setup at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const fixture = await mockSettings(page);
    try {
      await page.goto('/settings?tab=account');
      const disclosure = page.locator('details').filter({ hasText: 'Advanced: video spending limits' });
      await expect(disclosure).toBeVisible();
      await expect(disclosure).not.toHaveAttribute('open');
      expect(fixture.requests).not.toContain('/api/v1/videos/policy');
      await disclosure.locator('summary').click();
      await expect(page.getByLabel('Apply video spending limits')).not.toBeChecked();
      await expect(page.getByText('Conversation ID', { exact: true })).toHaveCount(0);
      await expect(disclosure.locator('textarea')).toHaveCount(0);
      await expect(page.getByLabel('Per video (USD)')).toHaveCount(0);
      await page.getByLabel('Apply video spending limits').check();
      await expect(page.getByLabel('Per video (USD)')).toBeVisible();
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`video-limits-${width}.png`), fullPage: true });
      await page.getByRole('tab', { name: 'routing', exact: true }).filter({ visible: true }).click();
      await expect(page.getByText('Advanced: video spending limits', { exact: true })).toHaveCount(0);
      await expect(page.getByText('Video provider jobs', { exact: true })).toHaveCount(0);
      expect(fixture.errors).toEqual([]);
    } finally { fixture.release(); }
  });

  test(`Settings opens and switches sections without zero-edit warnings at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const fixture = await mockSettings(page);
    const dialogs: string[] = [];
    page.on('dialog', async (dialog) => { dialogs.push(dialog.message()); await dialog.dismiss(); });
    try {
      await page.goto('/settings?tab=account');
      await expect(page.getByRole('button', { name: 'Change password', exact: true })).toBeVisible();
      expect(fixture.requests).not.toContain('/api/v1/llm-providers');
      expect(fixture.requests).not.toContain('/api/v1/system/diagnostics');
      await page.getByRole('tab', { name: 'providers', exact: true }).filter({ visible: true }).click();
      await expect(page.getByRole('heading', { name: 'LLM providers' })).toBeVisible();
      await expect(page.getByRole('dialog', { name: 'Discard unsaved changes?' })).toHaveCount(0);
      expect(fixture.requests).toContain('/api/v1/llm-providers');
      await page.locator('a[href="/tasks"]').filter({ visible: true }).first().click();
      await expect(page).toHaveURL(/\/tasks$/);
      expect(dialogs).toEqual([]);
      expect(fixture.errors).toEqual([]);
    } finally { fixture.release(); }
  });
}

test('Settings protects actual edits and stops warning after reverting them', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const fixture = await mockSettings(page);
  const dialogs: string[] = [];
  page.on('dialog', async (dialog) => { dialogs.push(dialog.message()); await dialog.dismiss(); });
  try {
    await page.goto('/settings');
    const name = page.getByPlaceholder('My OpenAI', { exact: true });
    await expect(name).toBeVisible();
    await name.fill('Unsaved provider');
    await page.locator('a[href="/tasks"]').filter({ visible: true }).first().click();
    await expect.poll(() => dialogs.length).toBe(1);
    expect(dialogs[0]).toBe('You have unsaved changes. Leave this page?');
    await expect(page).toHaveURL(/\/settings$/);
    await name.fill('');
    await page.locator('a[href="/tasks"]').filter({ visible: true }).first().click();
    await expect(page).toHaveURL(/\/tasks$/);
    expect(dialogs).toHaveLength(1);
  } finally { fixture.release(); }
});
