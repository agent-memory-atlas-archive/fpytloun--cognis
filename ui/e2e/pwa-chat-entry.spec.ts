import { expect, test } from '@playwright/test';
import { installTaskCockpitFixture } from './task-cockpit-fixture';

test.use({ serviceWorkers: 'block', viewport: { width: 1024, height: 768 } });

test('opens chat after delayed authentication without navigating through the dashboard', async ({ page }) => {
  await installTaskCockpitFixture(page);
  let releaseAuth!: () => void;
  const authReady = new Promise<void>((resolve) => { releaseAuth = resolve; });
  await page.route('**/api/auth/me', async (route) => {
    await authReady;
    await route.fulfill({ json: { email: 'owner@cognis.test', role: 'user', name: 'Owner' } });
  });
  await page.routeWebSocket('**/api/ws', (ws) => {
    ws.send(JSON.stringify({ type: 'authenticated' }));
    ws.onMessage((message) => {
      if (JSON.parse(String(message)).type === 'ping') ws.send(JSON.stringify({ type: 'pong' }));
    });
  });
  const errors: string[] = [];
  const requests: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => { if (request.url().includes('/api/')) requests.push(request.url()); });
  await page.goto('/chat');
  await expect(page.getByText('Loading workspace', { exact: true })).toBeVisible();
  releaseAuth();
  try {
    await expect(page).toHaveURL(/\/chat\/conv-task-chat$/);
  } finally {
    await test.info().attach('startup-diagnostics', {
      body: JSON.stringify({ errors, requests }), contentType: 'application/json',
    });
  }
  await expect(page.getByRole('button', { name: 'New conversation', exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
