import { expect, test } from '@playwright/test';

test('in-app deliverables and fullscreen follow app appearance, not saved reader mode', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  await page.addInitScript(() => localStorage.setItem('cognis-rich-viewer-theme', 'light'));
  await page.goto('/rich-deliverable-fixture?surface=embedded&capture=viewer');
  const document = page.getByTestId('rich-deliverable');
  await expect(document).toBeVisible();
  await page.evaluate(() => {
    window.document.documentElement.dataset.themeFamily = 'paper';
    window.document.documentElement.dataset.resolvedTheme = 'dark';
  });
  await expect(document).toHaveAttribute('data-viewer-theme', 'dark');
  await expect(document).toHaveAttribute('data-theme-family', 'paper');
  await page.getByRole('button', { name: 'Open full view', exact: true }).click();
  const full = page.locator('.rich-full');
  await expect(full).toHaveAttribute('data-viewer-theme', 'dark');
  await expect(page.getByRole('button', { name: /^Theme:/ })).toHaveCount(0);
  await page.evaluate(() => { window.document.documentElement.dataset.resolvedTheme = 'light'; });
  await expect(document).toHaveAttribute('data-viewer-theme', 'light');
  await expect(full).toHaveAttribute('data-viewer-theme', 'light');
});

test('external reader keeps independent switchable appearance', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.addInitScript(() => localStorage.setItem('cognis-rich-viewer-theme', 'light'));
  await page.goto('/rich-deliverable-fixture?surface=standalone&capture=viewer');
  const document = page.getByTestId('rich-deliverable');
  await expect(document).toHaveAttribute('data-viewer-theme', 'light');
  await page.getByRole('button', { name: 'Theme: light. Switch to dark theme' }).click();
  await expect(document).toHaveAttribute('data-viewer-theme', 'dark');
  await page.getByRole('button', { name: 'Theme: dark. Switch to system theme' }).click();
  await expect(document).toHaveAttribute('data-viewer-theme', 'dark');
  await page.emulateMedia({ colorScheme: 'light' });
  await expect(document).toHaveAttribute('data-viewer-theme', 'light');
});
