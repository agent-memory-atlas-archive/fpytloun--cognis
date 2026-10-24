import { expect, test } from '@playwright/test';
import { installLibraryFixture } from './library-fixture';

test.beforeEach(async ({ page }) => { await installLibraryFixture(page); });

test('favorite controls stay compact and borderless while remaining keyboard accessible', async ({ page }) => {
  await page.goto('/library?lib_kind=artifact&lib_group=none');
  const favorite = page.getByTestId('resource-row').first().locator('..').getByRole('button', { name: /favorites$/ });
  await expect(favorite).toBeEnabled();
  const rem = await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize));
  await expect(favorite).toHaveCSS('width', `${2 * rem}px`);
  await expect(favorite).toHaveCSS('border-top-width', '0px');
  await expect(favorite.locator('svg')).toHaveAttribute('width', '14');
  await favorite.focus();
  await expect(favorite).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(favorite).toHaveAttribute('aria-pressed', 'true');
  await page.screenshot({ path: test.info().outputPath('subtle-favorite-control.png'), fullPage: true });
});

for (const kind of ['artifact', 'deliverable'] as const) {
  test(`${kind} favorites work in list, preview and grouped Library`, async ({ page }) => {
    await page.goto(`/library?lib_kind=${kind}&lib_group=none`);
    const row = page.getByTestId('resource-row').first();
    const title = await row.locator('span.block').first().textContent();
    const add = row.locator('..').getByRole('button', { name: 'Add to favorites', exact: true });
    await add.click();
    await expect(row.locator('..').getByRole('button', { name: 'Remove from favorites' })).toHaveAttribute('aria-pressed', 'true');
    await page.getByRole('button', { name: 'Favorites', exact: true }).click();
    await expect(page.getByTestId('resource-row')).toHaveCount(1);
    await expect(page.getByTestId('resource-row')).toContainText(title!);
    await page.screenshot({ path: test.info().outputPath(`favorites-${kind}.png`), fullPage: true });
    await page.reload();
    await expect(page.getByRole('button', { name: 'Favorites', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('resource-row')).toHaveCount(1);
    await expect(page.getByRole('button', { name: 'Remove from favorites', exact: true })).toBeVisible();
    await page.getByRole('combobox', { name: 'View', exact: true }).selectOption('project');
    const folder = page.locator('[aria-busy] > div > button[aria-expanded]').first();
    await folder.click();
    await expect(page.getByTestId('resource-row')).toHaveCount(1);
    await page.getByTestId('resource-row').click();
    const modal = page.getByTestId('library-resource-modal');
    await modal.getByRole('button', { name: 'Remove from favorites' }).click();
    await expect(modal.getByRole('button', { name: 'Add to favorites' })).toHaveAttribute('aria-pressed', 'false');
    await page.getByRole('button', { name: /^Dismiss / }).click({ position: { x: 4, y: 4 } });
    await expect(modal).toHaveCount(0);
    await expect(page.getByTestId('resource-row')).toHaveCount(0);
  });
}

test('backdrop clicks do not discard Library edits or show an accidental discard prompt', async ({ page }) => {
  await page.route('**/api/v1/library/artifacts/*/edit', route => route.fulfill({
    json: { content: 'Original artifact content', filename: 'notes.txt', mime_type: 'text/plain' },
  }));
  await page.goto('/library?lib_kind=artifact&lib_group=none');
  await page.getByTestId('resource-row').filter({ hasText: 'Library requirements and acceptance notes.txt' }).click();
  const modal = page.getByTestId('library-resource-modal');
  await expect(modal.getByRole('button', { name: 'Edit', exact: true })).toBeVisible();
  await modal.getByRole('button', { name: 'Edit', exact: true }).click();
  const editor = modal.getByRole('textbox', { name: 'Artifact content' });
  // The edit endpoint is distinct from the preview endpoint.
  await expect(editor).toBeVisible();
  await editor.fill('Unsaved artifact edits');
  let confirmations = 0;
  page.on('dialog', async dialog => { confirmations++; await dialog.dismiss(); });
  await page.getByRole('button', { name: /^Dismiss / }).click({ position: { x: 4, y: 4 } });
  await expect(editor).toHaveText('Unsaved artifact edits');
  expect(confirmations).toBe(0);
  await modal.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: /^Dismiss / }).click({ position: { x: 4, y: 4 } });
  await expect(modal).toHaveCount(0);
});

test('task creation also allows clean dismissal but preserves a partially written task', async ({ page }) => {
  await page.goto('/tasks');
  await page.getByRole('button', { name: 'Create task', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Create task', exact: true });
  await expect(dialog.getByLabel('Title', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Dismiss Create task', exact: true }).click({ position: { x: 4, y: 4 } });
  await expect(dialog).toHaveCount(0);
  await page.getByRole('button', { name: 'Create task', exact: true }).click();
  await dialog.getByLabel('Title', { exact: true }).fill('Do not lose this task');
  await page.getByRole('button', { name: 'Dismiss Create task', exact: true }).click({ position: { x: 4, y: 4 } });
  await expect(dialog.getByLabel('Title', { exact: true })).toHaveValue('Do not lose this task');
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(dialog).toHaveCount(0);
});
