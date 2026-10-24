import { expect, test } from '@playwright/test';
import { installTaskCockpitFixture } from './task-cockpit-fixture';

for (const width of [390, 1440]) {
  test(`executor issue diagnostics and recovery at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route('**/api/auth/**', (route) => route.fulfill({
      json: { email: 'owner@example.com', name: 'Owner', role: 'user' }
    }));
    await installTaskCockpitFixture(page);
    const executor = {
      executor_id: 'diagnostics-host', name: 'Diagnostics host', executor_type: 'websocket',
      available: true, shared: false, owner_email: 'owner@example.com',
      status: 'active', runtime_state: 'degraded', desired_config_version: 7,
      applied_config_version: 7, runtime_metadata: { mcp_servers: [{
        name: 'hass', status: 'failed', phase: 'initialize', error_class: 'timeout',
        timed_out: true, message: 'MCP initialize timed out after 15s',
        stderr_summary: 'Waiting for startup dependencies'
      }] }
    };
    let requested = false;
    await page.route('**/api/v1/executors/diagnostics-host**', (route) => {
      if (route.request().method() === 'POST') {
        requested = true;
        return route.fulfill({ status: 202, json: {
          ...executor, runtime_state: 'reconfiguring', desired_config_version: 8
        } });
      }
      return route.fulfill({ json: requested ? {
        ...executor, runtime_state: 'active', desired_config_version: 8,
        applied_config_version: 8, runtime_metadata: {}
      } : executor });
    });
    await page.route('**/api/v1/dashboard/issues', (route) => route.fulfill({ json: {
      generated_at: '2026-10-01T07:00:00Z',
      summary: { total: 1, warning: 1, critical: 0, info: 0, truncated: false },
      issues: [{ id: 'executor-diagnostics', severity: 'warning', kind: 'executor_degraded',
        title: 'Diagnostics host is degraded', detail: 'Degraded runtime', observed_at: null,
        resource: { type: 'executor', id: executor.executor_id, label: executor.name },
        action_url: '/settings?tab=executors' }]
    } }));
    await page.goto('/');
    const issue = page.getByTestId('dashboard-issue-executor-diagnostics');
    await issue.getByRole('button', { name: 'Show details' }).click();
    await expect(issue.getByText(/hass: initialize.*MCP initialize timed out after 15s/)).toBeVisible();
    await issue.getByRole('button', { name: 'Retry configuration' }).click();
    await expect(issue.getByText(/Configuration retry requested/)).toBeVisible();
    await issue.getByRole('button', { name: 'Refresh status' }).click();
    await expect(issue.getByText('No detailed runtime failures reported.')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}
