import { expect, test, type Page } from '@playwright/test';

test.use({
  serviceWorkers: 'block',
  // Static preview lacks the controller's generated CSP hashes for bootstrap.
  // This suite exercises mocked editor behavior, not the deployment CSP.
  bypassCSP: process.env.COGNIS_E2E_STATIC_PREVIEW === '1',
});

async function editorFixture(page: Page) {
  let agent: Record<string, unknown> = {
    agent_id: 'editor-agent', name: 'Editor agent', owner_email: 'owner@cognis.local',
    agent_type: 'primary', status: 'draft', personality_synced: true,
    is_system: false, is_readonly_for_caller: false, is_shared_with_me: false,
    tools: {}, permissions: {}, execution: {}, llm_config: {}, agent_profiles: {},
    avatar_url: '/agent-photo.svg',
  };
  let hookAssignments: Record<string, unknown>[] = [];
  await page.route('**/agent-photo.svg', route => route.fulfill({
    contentType: 'image/svg+xml',
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" rx="16" fill="#075985"/><text x="32" y="41" text-anchor="middle" fill="white" font-size="24">EA</text></svg>',
  }));
  const requests: string[] = [];
  const saves: Record<string, unknown>[] = [];
  const errors: string[] = [];
  page.on('pageerror', error => { errors.push(error.message); console.error(error.stack); });
  page.on('console', message => { if (message.type() === 'error') console.error(message.text()); });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    requests.push(`${method} ${path}`);
    let body: unknown = [];
    if (path === '/api/auth/me') body = { email: 'owner@cognis.local', name: 'Owner', role: 'user' };
    else if (path === '/api/health') body = { status: 'ok', services: {}, llm_available: true };
    else if (path === '/api/bootstrap-status') body = { has_users: true, needs_bootstrap: false };
    else if (path === '/api/v1/dashboard/navigation-summary') body = {
      chat_groups: [], dashboard: { total: 0, critical: 0, warning: 0 }, schedules: 0, tasks: 0,
    };
    else if (path === '/api/v1/agents') body = { items: [agent], cursor: null, has_more: false };
    else if (path === '/api/v1/agents/editor-agent') {
      if (method === 'PUT') {
        const payload = route.request().postDataJSON();
        saves.push(payload);
        agent = { ...agent, ...payload };
      }
      body = agent;
    } else if (path === '/api/v1/agents/editor-agent/activate') {
      agent = { ...agent, status: 'active' };
      body = agent;
    } else if (path === '/api/v1/agents/editor-agent/projects') {
      body = [{ project_id: 'editor-project', project_name: 'Engineering', executor_scope: 'owner_executor' }];
    } else if (path === '/api/v1/hooks') body = { items: [{
      hook_id: 'system:recall-reminder', name: 'Recall relevant memories', bundled: true,
    }] };
    else if (path === '/api/v1/agents/editor-agent/hooks') {
      if (method === 'PUT') {
        body = route.request().postDataJSON();
        hookAssignments = [body as Record<string, unknown>];
      } else body = { items: hookAssignments };
    }
    else if (path.endsWith('/memory-backends')) body = { items: [{
      id: 'mnemory', display_name: 'Mnemory', description: 'Persistent personal and agent memory.',
      defaults: { mode: 'full_auto' }, merge_semantics: 'shallow_field_override',
      modes: [{ id: 'full_auto', label: 'Full auto', description: 'Automatic recall and remembering.',
        recommended_for: 'Personal assistants and long-lived general agents.', tooltip: '',
        behavior: { core_bootstrap: true, auto_recall: true, auto_remember: true, tools: true },
      }],
    }] };
    else if (path === '/api/v1/agents/effective-tools/preview') body = { configured_state: { tools: [
      { name: 'read', tool_id: 'read', category: 'filesystem', description: 'Read files', source: { type: 'builtin' } },
    ] } };
    else if (path === '/api/v1/inference-routes') body = { routes: [] };
    else if (path.endsWith('/sidebar')) body = {
      agents: [agent], agent_direct_chats: [], context_types: ['web'],
      conversations: { items: [], next_cursor: null, has_more: false },
      background_work: { items: [], truncated: false },
    };
    else if (path === '/api/v1/workflows' || path === '/api/v1/llm-providers') body = { items: [], cursor: null, has_more: false };
    await route.fulfill({ json: body });
  });
  await page.routeWebSocket('**/api/ws', ws => ws.send(JSON.stringify({ type: 'authenticated' })));
  return { requests, saves, errors };
}

for (const width of [390, 1440]) {
  test(`agent settings stay under one tab bar and preserve drafts at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const fixture = await editorFixture(page);
    await page.goto('/agents/editor-agent');
    const name = page.getByPlaceholder('Research Assistant');
    await expect(name).toBeVisible();
    const headerAvatar = page.locator('main header').getByRole('img', { name: 'Editor agent' });
    await expect(headerAvatar).toBeVisible();
    await expect(headerAvatar).toHaveJSProperty('naturalWidth', 64);
    await page.screenshot({ path: testInfo.outputPath(`header-${width}.png`) });
    await page.getByRole('tab', { name: 'Providers & models', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Memory', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Guardrails', exact: true })).toBeVisible();
    await expect(page.getByRole('combobox', { name: /^Minimum evaluation outcome/ })).not.toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`providers-${width}.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.getByRole('tab', { name: 'Identity', exact: true }).click();
    const save = page.getByRole('button', { name: 'Save changes', exact: true });
    await expect(save).toBeDisabled();
    expect(fixture.requests.some(request => /\/hooks$|\/projects$|\/shares$|effective-tools/.test(request))).toBe(false);
    await expect(page.getByRole('tablist', { name: 'Agent configuration' })).toHaveCount(1);
    await name.fill('Draft identity');
    await expect(save).toBeEnabled();
    await page.getByRole('button', { name: 'Activate', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Suspend', exact: true })).toBeVisible();
    await expect(name).toHaveValue('Draft identity');
    const identityTab = page.getByRole('tab', { name: 'Identity', exact: true });
    await identityTab.focus();
    await page.keyboard.press('End');
    const collaboration = page.getByRole('tab', { name: 'Collaboration', exact: true });
    await expect(collaboration).toHaveAttribute('aria-selected', 'true');
    await expect(collaboration).toBeFocused();
    await expect(page.getByRole('heading', { name: 'Project assignments' })).toBeVisible();
    await expect(page.getByRole('link', { name: /Engineering/ })).toHaveAttribute('href', '/projects/editor-project?tab=agents');
    await expect(page.getByRole('heading', { name: 'Agent status' })).not.toBeVisible();
    expect(await page.locator('form form').count()).toBe(0);
    await page.getByRole('tab', { name: 'Hooks', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Hooks', exact: true })).toBeVisible();
    await expect(page.getByText(/Applies immediately/)).toHaveCount(0);
    await page.getByRole('combobox', { name: 'Hook to assign' }).selectOption('system:recall-reminder');
    await page.getByRole('button', { name: 'Enable hook', exact: true }).click();
    await expect(page.getByRole('checkbox', { name: 'Enabled', exact: true })).toBeChecked();
    await expect(page.getByText('Hook enabled.', { exact: true })).toBeVisible();
    await page.getByRole('checkbox', { name: 'Enabled', exact: true }).click();
    await expect(page.getByText('Hook disabled.', { exact: true })).toBeVisible();
    await expect(page.getByRole('checkbox', { name: 'Enabled', exact: true })).not.toBeChecked();
    await save.click();
    await expect(save).toBeDisabled();
    expect(fixture.saves).toHaveLength(1);
    expect(fixture.saves[0].name).toBe('Draft identity');
    await expect(page.getByRole('tab', { name: 'Hooks', exact: true })).toHaveAttribute('aria-selected', 'true');
    expect(fixture.requests.filter(request => request === 'GET /api/v1/hooks')).toHaveLength(1);
    await page.screenshot({ path: testInfo.outputPath(`hooks-${width}.png`) });
    await page.getByRole('tab', { name: /^Tools/ }).click();
    await expect(page.getByRole('searchbox')).toBeVisible();
    await expect(save).toBeDisabled();
    await page.getByRole('searchbox').fill('read');
    const permission = page.getByRole('combobox', { name: 'Permission for read' });
    await permission.selectOption('deny');
    await expect(save).toBeEnabled();
    await permission.selectOption('');
    await expect(save).toBeDisabled();
    await identityTab.click();
    await expect(name).toHaveValue('Draft identity');
    await page.screenshot({ path: testInfo.outputPath(`identity-${width}.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(fixture.errors).toEqual([]);
  });
}
