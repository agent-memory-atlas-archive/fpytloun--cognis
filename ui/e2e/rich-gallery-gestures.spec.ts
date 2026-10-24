import { readFileSync } from 'node:fs';
import { basename, resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const build = resolve('standalone-build');
const entry = JSON.parse(readFileSync(resolve(build, '.vite/manifest.json'), 'utf8'))['src/standalone.ts'];
const fixture = {
  title: 'Gallery gestures',
  content: '',
  instanceId: '',
  payload: { blocks: [{ type: 'figure', src: '/gesture-diagram.svg', alt: 'Architecture diagram' }] },
};

async function openGallery(page: Page, open = true) {
  await page.route('**/gesture-diagram.svg', route => route.fulfill({
    contentType: 'image/svg+xml',
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="1200"><rect width="1800" height="1200" fill="white"/><text x="40" y="60">Architecture</text></svg>',
  }));
  await page.route('**/standalone-assets/assets/*', route => {
    const file = basename(new URL(route.request().url()).pathname);
    return route.fulfill({ body: readFileSync(resolve(build, 'assets', file)), contentType: file.endsWith('.css') ? 'text/css' : file.endsWith('.woff2') ? 'font/woff2' : 'text/javascript' });
  });
  await page.route('**/gallery-gestures', route => route.fulfill({
    contentType: 'text/html; charset=utf-8',
    body: `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">${entry.css.map((file: string) => `<link rel="stylesheet" href="/standalone-assets/${file}">`).join('')}</head><body><div id="cognis-deliverable-root"></div><template id="cognis-deliverable-payload">${JSON.stringify(fixture)}</template><script type="module" src="/standalone-assets/${entry.file}"></script></body></html>`,
  }));
  await page.goto('/gallery-gestures');
  const trigger = page.getByRole('button', { name: 'Enlarge image: Architecture diagram' });
  if (open) await trigger.click();
  const dialog = page.getByRole('dialog');
  if (open) {
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Zoom in' })).toBeEnabled();
  }
  return { dialog, image: dialog.locator('img'), canvas: dialog.locator('.image-canvas'), trigger };
}

test('failed lazy preview load keeps the figure visible and reports a retry path', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const { trigger } = await openGallery(page, false);
  await page.route('**/standalone-assets/assets/ImageViewer-*.js', route => route.abort());
  await trigger.click();
  await expect(page.getByRole('status')).toHaveText('Image preview could not load. Reload the page to retry.');
  await expect(trigger.locator('img')).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('desktop click anchors zoom, mouse movement pans to both edges, click resets', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const { image, canvas, dialog } = await openGallery(page);
  const fit = (await image.boundingBox())!;
  const point = { x: fit.x + fit.width * .3, y: fit.y + fit.height * .4 };
  await page.mouse.click(point.x, point.y);
  await expect(image).toHaveClass(/zoomed/);
  const enlarged = (await image.boundingBox())!;
  expect(Math.abs(enlarged.x + enlarged.width * .3 - point.x)).toBeLessThan(2);
  expect(Math.abs(enlarged.y + enlarged.height * .4 - point.y)).toBeLessThan(2);
  const before = await canvas.evaluate(node => ({ x: node.scrollLeft, y: node.scrollTop }));
  await page.mouse.move(1380, 850, { steps: 5 });
  const right = await canvas.evaluate(node => ({ x: node.scrollLeft, y: node.scrollTop }));
  expect(right.x).toBeGreaterThan(before.x);
  expect(right.y).toBeGreaterThan(before.y);
  await page.mouse.move(25, 73, { steps: 5 });
  const left = await canvas.evaluate(node => ({ x: node.scrollLeft, y: node.scrollTop }));
  expect(left.x).toBeLessThan(right.x);
  expect(left.y).toBeLessThan(right.y);
  await page.mouse.click(500, 300);
  await expect(image).not.toHaveClass(/zoomed/);
  expect(await canvas.evaluate(node => node.scrollLeft + node.scrollTop)).toBe(0);
  await expect(dialog).toBeVisible();
});

test('touch taps zoom and reset without compatibility-click dismissal', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  const { dialog, image, trigger } = await openGallery(page);
  const fit = (await image.boundingBox())!;
  const point = { x: fit.x + fit.width / 2, y: fit.y + fit.height / 2 };
  await page.touchscreen.tap(point.x, point.y);
  await page.touchscreen.tap(point.x, point.y);
  await expect(image).toHaveClass(/zoomed/);
  await expect(dialog).toBeVisible();
  await page.touchscreen.tap(point.x, point.y);
  await page.touchscreen.tap(point.x, point.y);
  await expect(image).not.toHaveClass(/zoomed/);
  await dialog.getByRole('button', { name: 'Close image preview' }).tap();
  await expect(trigger).toBeFocused();
  await context.close();
});

for (const viewport of [{ width: 390, height: 844 }, { width: 844, height: 390 }]) {
  test(`mobile double-tap, drag, pinch and reset at ${viewport.width}px`, async ({ browser }) => {
    const context = await browser.newContext({ viewport, isMobile: true, hasTouch: true });
    const page = await context.newPage();
    const { dialog, image, canvas, trigger } = await openGallery(page);
    const cdp = await context.newCDPSession(page);
    const fit = (await image.boundingBox())!;
    const point = { x: fit.x + fit.width / 2, y: fit.y + fit.height / 2 };
    await page.touchscreen.tap(point.x, point.y);
    await expect(image).not.toHaveClass(/zoomed/);
    await page.touchscreen.tap(point.x, point.y);
    await expect(image).toHaveClass(/zoomed/);
    const before = await canvas.evaluate(node => ({ x: node.scrollLeft, y: node.scrollTop }));
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ ...point, id: 1 }] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: point.x - 70, y: point.y - 30, id: 1 }] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    const after = await canvas.evaluate(node => ({ x: node.scrollLeft, y: node.scrollTop }));
    expect(after.x).toBeGreaterThan(before.x + 60);
    expect(after.y).toBeGreaterThan(before.y + 20);
    await expect(dialog).toBeVisible();
    await expect(image).toHaveClass(/zoomed/);
    await page.touchscreen.tap(point.x, point.y);
    await page.touchscreen.tap(point.x, point.y);
    await expect(image).not.toHaveClass(/zoomed/);

    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [
      { x: point.x - 40, y: point.y, id: 1 }, { x: point.x + 40, y: point.y, id: 2 },
    ] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [
      { x: point.x - 100, y: point.y, id: 1 }, { x: point.x + 100, y: point.y, id: 2 },
    ] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await expect(image).toHaveClass(/zoomed/);
    const pinched = (await image.boundingBox())!;
    expect(pinched.width).toBeGreaterThan(fit.width * 2);
    expect(Math.abs(pinched.x + pinched.width / 2 - point.x)).toBeLessThan(2);
    expect(Math.abs(pinched.y + pinched.height / 2 - point.y)).toBeLessThan(2);
    expect(await page.evaluate(() => window.visualViewport?.scale)).toBe(1);
    await expect(dialog).toBeVisible();
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [
      { x: point.x - 100, y: point.y, id: 1 }, { x: point.x + 100, y: point.y, id: 2 },
    ] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [
      { x: point.x - 30, y: point.y, id: 1 }, { x: point.x + 30, y: point.y, id: 2 },
    ] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await expect(image).not.toHaveClass(/zoomed/);
    await page.touchscreen.tap(point.x, point.y);
    await page.touchscreen.tap(point.x, point.y);
    await expect(image).toHaveClass(/zoomed/);
    await page.setViewportSize({ width: viewport.height, height: viewport.width });
    await expect(image).not.toHaveClass(/zoomed/);
    await dialog.getByRole('button', { name: 'Zoom in' }).tap();
    await expect(image).toHaveClass(/zoomed/);
    const rotated = (await image.boundingBox())!;
    const canceledPoint = { x: Math.max(50, Math.min(viewport.height - 50, rotated.x + rotated.width / 2)), y: viewport.width / 2 };
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ ...canceledPoint, id: 1 }] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchCancel', touchPoints: [] });
    await expect(dialog).toBeVisible();
    await expect(image).toHaveClass(/zoomed/);
    await dialog.getByRole('button', { name: 'Zoom out' }).tap();
    await expect(image).not.toHaveClass(/zoomed/);
    await dialog.getByRole('button', { name: 'Close image preview' }).tap();
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await context.close();
  });
}
