import { expect, type Locator } from '@playwright/test';

export async function selectViewerTheme(viewer: Locator, mode: 'light' | 'dark' | 'system') {
  const control = viewer.locator('.theme-control');
  for (let step = 0; step < 3; step++) {
    if (await control.getAttribute('data-theme-mode') === mode) break;
    await control.click();
  }
  await expect(control).toHaveAttribute('data-theme-mode', mode);
}
