import { readFileSync } from 'node:fs';
import { basename, resolve } from 'node:path';
import { expect, test } from '@playwright/test';

const build = resolve('standalone-build');
const entry = JSON.parse(readFileSync(resolve(build, '.vite/manifest.json'), 'utf8'))['src/standalone.ts'];
const fixture = {
  title: 'Sample release catalog — Design proposal',
  content: '',
  instanceId: '',
  payload: { blocks: [
    { type: 'markdown', content: 'Draft design proposal.\n\n' + Array.from({ length: 11 }, (_, i) =>
      `## ${i + 1}. Section\n\n${'Design details and acceptance evidence. '.repeat(15)}`
    ).join('\n\n') },
    { type: 'figure', src: '/authorized-diagram.svg', alt: 'Catalog architecture', title: 'Architecture' },
  ] },
};

for (const width of [390, 1440]) {
  test(`document navigation and image viewer at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route('**/authorized-diagram.svg', route => route.fulfill({
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="900"><rect width="1800" height="900" fill="white"/><text x="40" y="60">Catalog architecture</text></svg>',
    }));
    await page.route('**/standalone-assets/assets/*', route => {
      const file = basename(new URL(route.request().url()).pathname);
      return route.fulfill({ body: readFileSync(resolve(build, 'assets', file)), contentType: file.endsWith('.css') ? 'text/css' : file.endsWith('.woff2') ? 'font/woff2' : 'text/javascript' });
    });
    await page.route('**/document-images', route => route.fulfill({
      contentType: 'text/html; charset=utf-8',
      body: `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">${entry.css.map((file: string) => `<link rel="stylesheet" href="/standalone-assets/${file}">`).join('')}</head><body><div id="cognis-deliverable-root"></div><template id="cognis-deliverable-payload">${JSON.stringify(fixture)}</template><script type="module" src="/standalone-assets/${entry.file}"></script></body></html>`,
    }));
    await page.goto('/document-images');
    await expect(page.locator('.rich-toolbar h1')).toHaveCount(0);
    await expect(page.locator('.rich-body > .document-title')).toHaveText(fixture.title);
    expect(await page.locator('.document-title').evaluate(node => parseFloat(getComputedStyle(node).fontSize))).toBeLessThanOrEqual(44);
    const chrome = page.getByTestId('rich-viewer-chrome');
    const theme = chrome.locator('.theme-control');
    await expect(theme).toHaveCount(1);
    for (const mode of ['light', 'dark', 'system']) {
      await theme.click();
      await expect(theme).toHaveAttribute('data-theme-mode', mode);
      await expect(theme.locator('svg')).toHaveAttribute('data-viewer-icon', mode);
      expect(await page.evaluate(() => localStorage.getItem('cognis-rich-viewer-theme'))).toBe(mode);
    }
    await page.emulateMedia({ colorScheme: 'dark' });
    await expect(page.getByTestId('rich-deliverable')).toHaveAttribute('data-viewer-theme', 'dark');
    if (width === 1440) {
      await page.locator('aside.rich-toc').getByRole('button', { name: 'Close table of contents' }).click();
    }
    const openToc = page.getByRole('button', { name: 'Open table of contents' });
    const tocBox = await openToc.boundingBox();
    const titleBox = await chrome.locator('.viewer-title').boundingBox();
    const themeBox = await theme.boundingBox();
    expect(tocBox!.width).toBe(themeBox!.width);
    expect(tocBox!.height).toBe(themeBox!.height);
    if (width === 1440) {
      expect(tocBox!.x).toBeLessThan(titleBox!.x);
      await expect(openToc.locator('svg')).toHaveAttribute('data-viewer-icon', 'expand');
      await page.setViewportSize({ width: 390, height: 900 });
      await expect(openToc.locator('svg')).toHaveAttribute('data-viewer-icon', 'contents');
      await openToc.click();
      await expect(page.getByRole('dialog', { name: 'Table of contents' })).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(openToc).toBeFocused();
      await page.setViewportSize({ width: 1440, height: 900 });
      await expect(openToc.locator('svg')).toHaveAttribute('data-viewer-icon', 'expand');
    } else {
      expect(tocBox!.x).toBeGreaterThan(titleBox!.x);
      await expect(openToc.locator('svg')).toHaveAttribute('data-viewer-icon', 'contents');
      await openToc.click();
      await expect(page.getByRole('dialog', { name: 'Table of contents' })).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(openToc).toBeFocused();
    }
    if (await openToc.isVisible()) await openToc.click();
    await page.getByRole('button', { name: '11. Section', exact: true }).click();
    const section = page.getByRole('heading', { name: '11. Section', exact: true });
    await expect(section).toBeFocused();
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
    const trigger = page.getByRole('button', { name: 'Enlarge image: Catalog architecture' });
    await trigger.focus();
    await page.keyboard.press('Enter');
    const dialog = page.getByRole('dialog', { name: 'Architecture' });
    await expect(dialog).toBeVisible();
    const originalSrc = await dialog.locator('img').getAttribute('src');
    await page.emulateMedia({ colorScheme: 'light' });
    await expect(dialog).toHaveAttribute('data-viewer-theme', 'light');
    await page.emulateMedia({ colorScheme: 'dark' });
    await expect(dialog).toHaveAttribute('data-viewer-theme', 'dark');
    await expect(dialog.locator('img')).toHaveAttribute('src', originalSrc!);
    expect(await dialog.locator('img').evaluate(node => getComputedStyle(node).filter)).toBe('none');
    await expect(dialog.locator('header')).toHaveCount(0);
    await expect(dialog.locator('.image-controls button')).toHaveCount(2);
    expect(await dialog.evaluate(node => getComputedStyle(node).borderTopWidth)).toBe('0px');
    await expect(dialog.locator('img')).toHaveAttribute('src', await trigger.locator('img').getAttribute('src') as string);
    const fittedImage = await dialog.locator('img').boundingBox();
    expect(fittedImage!.width).toBeLessThan(width);
    await dialog.getByRole('button', { name: 'Zoom in' }).click();
    await expect(dialog.locator('img')).toHaveClass(/zoomed/);
    await expect(dialog.getByRole('button', { name: 'Zoom out' })).toHaveAttribute('aria-pressed', 'true');
    expect((await dialog.locator('img').boundingBox())!.width).toBe(Math.max(1800, fittedImage!.width * 2));
    await dialog.getByRole('button', { name: 'Zoom out' }).click();
    await expect(dialog.locator('img')).not.toHaveClass(/zoomed/);
    await dialog.getByRole('button', { name: 'Zoom image', exact: true }).click();
    await expect(dialog.locator('img')).toHaveClass(/zoomed/);
    await dialog.getByRole('button', { name: 'Zoom out' }).click();
    for (let i = 0; i < 5; i++) await page.keyboard.press('Tab');
    expect(await dialog.evaluate(node => node.contains(document.activeElement))).toBe(true);
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await trigger.click();
    await page.getByRole('button', { name: 'Close image preview' }).click();
    await expect(trigger).toBeFocused();
    await trigger.click();
    await dialog.click({ position: { x: 4, y: 100 } });
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  });
}
