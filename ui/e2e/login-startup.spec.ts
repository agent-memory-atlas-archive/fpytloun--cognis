import { expect, test } from '@playwright/test';

test('login stays on the loading screen until session verification finishes', async ({ page }) => {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  let requested!: () => void;
  const requestStarted = new Promise<void>((resolve) => { requested = resolve; });
  await page.route('**/api/auth/me', async (route) => {
    requested();
    await pending;
    await route.fulfill({ status: 401, json: { detail: 'Unauthenticated' } });
  });
  await page.goto('/login');
  await requestStarted;
  await expect(page.getByText('Loading workspace', { exact: true })).toBeVisible();
  await expect(page.locator('input[name="email"]')).toHaveCount(0);
  release();
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
});
