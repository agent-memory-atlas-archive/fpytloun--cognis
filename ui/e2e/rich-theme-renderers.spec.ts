import { expect, test } from '@playwright/test';

test('live app theme updates canvas and Mermaid and then settles', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.addInitScript(() => localStorage.removeItem('cognis-rich-viewer-theme'));
  await page.goto('/rich-deliverable-fixture?scenario=every-block-reference&surface=embedded&capture=viewer');
  const viewer = page.getByTestId('rich-deliverable');
  const chart = viewer.locator('[data-chart-ready="true"] canvas').first();
  const diagram = viewer.locator('.rich-mermaid svg').first();
  await expect(chart).toBeVisible();
  await expect(diagram).toBeAttached();
  const canvasPixels = () => chart.evaluate((node: HTMLCanvasElement) => node.toDataURL());
  const diagramColors = () => diagram.evaluate(node => node.outerHTML);
  await page.evaluate(() => document.documentElement.setAttribute('data-resolved-theme', 'dark'));
  await expect(viewer).toHaveAttribute('data-viewer-theme', 'dark');
  const darkCanvas = await canvasPixels();
  const darkDiagram = await diagramColors();
  await page.evaluate(() => document.documentElement.setAttribute('data-resolved-theme', 'light'));
  await expect(viewer).toHaveAttribute('data-viewer-theme', 'light');
  await expect.poll(canvasPixels).not.toBe(darkCanvas);
  await expect.poll(diagramColors).not.toBe(darkDiagram);
  // Identity stability after rendering catches observer-driven replacement loops.
  const stable = await diagram.elementHandle();
  await page.waitForTimeout(500);
  expect(await stable!.evaluate(node => node.isConnected)).toBe(true);
  const stableCanvas = await canvasPixels();
  await page.waitForTimeout(500);
  expect(await canvasPixels()).toBe(stableCanvas);
  await page.screenshot({ path: '/tmp/cognis-rich-renderers-light.png', fullPage: true });
});
