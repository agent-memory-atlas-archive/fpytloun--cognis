import { expect, test } from '@playwright/test';

for (const width of [360, 390, 768, 1024, 1440]) {
  test(`standalone theme and overflow at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`/rich-deliverable-fixture?scenario=design-document-composed&surface=standalone&width=${width}`);
    const viewer = page.getByTestId('rich-deliverable');
    for (const theme of ['light', 'dark']) {
      await viewer.getByRole('button', { name: theme === 'light' ? 'Light theme' : 'Dark theme' }).click();
      await expect(viewer).toHaveAttribute('data-viewer-theme', theme);
      expect(await viewer.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      if (width === 390 || width === 1440) {
        await viewer.evaluate(el => el.scrollIntoView({ block: 'start' }));
        await viewer.screenshot({ path: `/tmp/rich-viewer-${theme}-${width}.png` });
      }
    }
    await viewer.getByRole('button', { name: 'Follow system theme' }).click();
    await page.emulateMedia({ colorScheme: 'light' });
    await expect(viewer).toHaveAttribute('data-viewer-theme', 'light');
    await page.emulateMedia({ colorScheme: 'dark' });
    await expect(viewer).toHaveAttribute('data-viewer-theme', 'dark');
  });
}

test('embedded full-view theme and keyboard close', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 1000 });
  await page.goto('/rich-deliverable-fixture?scenario=design-document-composed&surface=embedded&theme=light');
  const viewer = page.getByTestId('rich-deliverable');
  await expect(viewer).not.toHaveAttribute('data-viewer-theme');
  await viewer.getByRole('button', { name: 'Open table of contents' }).click();
  await expect(page.getByRole('dialog', { name: 'Table of contents' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'Table of contents' })).toHaveCount(0);
  const trigger = viewer.getByRole('button', { name: 'Open full view' });
  await trigger.click();
  const full = page.getByTestId('rich-deliverable-full-view');
  await expect(full.getByTestId('rich-viewer-identity')).toHaveText('ORBIT');
  await full.getByRole('button', { name: 'Dark theme' }).click();
  await expect(full).toHaveAttribute('data-viewer-theme', 'dark');
  await page.keyboard.press('Escape');
  await expect(full).toHaveCount(0);
  await expect(trigger).toBeFocused();
});
