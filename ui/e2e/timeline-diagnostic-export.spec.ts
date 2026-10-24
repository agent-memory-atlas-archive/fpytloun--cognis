import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

test('downloads local row origins and ordering without exporting message bodies', async ({ page }, testInfo) => {
  await page.goto('/timeline-diagnostic-fixture');
  const runtimeDetails = page.getByTestId('session-details-diagnostics');
  await expect(runtimeDetails).toBeVisible();
  const details = page.getByTestId('timeline-diagnostic-export');
  await expect(details).toBeHidden();
  await runtimeDetails.locator('summary').click();
  await expect(details).toBeVisible();
  await expect(details).toContainText('The file stays on your device unless you share it.');
  const button = details.getByRole('button', { name: 'Download chat diagnostics' });
  await button.focus();
  await expect(button).toBeFocused();
  const bounds = await button.boundingBox();
  expect(bounds?.height).toBeGreaterThanOrEqual(testInfo.project.use.isMobile ? 44 : 30);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('session-diagnostics.png'), fullPage: true });
  const apiRequests: string[] = [];
  page.on('request', request => {
    if (new URL(request.url()).pathname.startsWith('/api/')) apiRequests.push(request.method());
  });
  const downloadReady = page.waitForEvent('download');
  await details.getByRole('button', { name: 'Download chat diagnostics' }).click();
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe('cognis-chat-diagnostic-diagnostic-fixture.json');
  const path = await download.path();
  if (!path) throw new Error('Diagnostic download did not produce a file');
  const body = await readFile(path, 'utf8');
  const capture = JSON.parse(body);
  expect(capture.schema).toBe('cognis-chat-client-diagnostic-v1');
  expect(capture.scope.key).toBe('conversation:diagnostic-fixture');
  expect(capture.local_items[0].id).toBe('user:diagnostic-fixture');
  expect(capture.visible_items[0].sort_key).toMatch(/^9995:/);
  expect(capture.canonical_items).toEqual([]);
  expect(body).not.toContain('Synthetic message body excluded from diagnostics');
  expect(body).not.toContain('"content"');
  expect(apiRequests).toEqual([]);
});

test('shows a preparation error without navigating away or mutating chat state', async ({ page }) => {
  await page.goto('/timeline-diagnostic-fixture');
  await page.getByTestId('session-details-diagnostics').locator('summary').click();
  const details = page.getByTestId('timeline-diagnostic-export');
  await expect(details).toBeVisible();
  await page.evaluate(() => {
    URL.createObjectURL = () => { throw new Error('Synthetic unavailable download'); };
  });
  await details.getByRole('button', { name: 'Download chat diagnostics' }).click();
  await expect(details.getByRole('alert')).toContainText('Could not prepare the diagnostic file');
  await expect(page).toHaveURL(/timeline-diagnostic-fixture$/);
  await expect(details.getByRole('button', { name: 'Download chat diagnostics' })).toBeEnabled();
});
