import { readFileSync } from 'node:fs';
import { resolve, basename } from 'node:path';
import { expect, test } from '@playwright/test';

const build = resolve('standalone-build');
const entry = JSON.parse(readFileSync(resolve(build, '.vite/manifest.json'), 'utf8'))['src/standalone.ts'];
for (const width of [390, 1440]) {
  test(`Markdown tables and claims stay within the document at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route('**/standalone-assets/assets/*', route => {
      const file = basename(new URL(route.request().url()).pathname);
      return route.fulfill({ body: readFileSync(resolve(build, 'assets', file)), contentType: file.endsWith('.css') ? 'text/css' : file.endsWith('.woff2') ? 'font/woff2' : 'text/javascript' });
    });
    const fixture = {
      title: 'Audit report',
      content: '',
      instanceId: '',
      payload: { blocks: [
        { type: 'markdown', content: '# Audit\n\nReadable prose stays narrow.\n\n| Dimension | First | Second | Third | Fourth |\n| --- | --- | --- | --- | --- |\n| Recovery | Durable history | Restorable checkpoints | Source-visible replacement | Persistent project rules |\n| Cache | Stable prefix | Stateful projection | Explicit replacement | Reuse |' },
        { type: 'evidence_report', claims: [{ claim: 'A long claim that must wrap within the available mobile width.', confidence: 'high', sources: [{ url: 'https://raw.githubusercontent.com/argoproj/argo-cd/master/docs/operator-manual/upgrading/overview.md' }] }] },
        { type: 'checklist', items: [{ text: 'Verify the backup before proceeding' }] },
      ] },
    };
    await page.route('**/rendering-gaps', route => route.fulfill({
      contentType: 'text/html',
      body: `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">${entry.css.map((file: string) => `<link rel="stylesheet" href="/standalone-assets/${file}">`).join('')}</head><body><div id="cognis-deliverable-root"></div><template id="cognis-deliverable-payload">${JSON.stringify(fixture)}</template><script type="module" src="/standalone-assets/${entry.file}"></script></body></html>`,
    }));
    await page.goto('/rendering-gaps');
    await expect(page.locator('.rich-toolbar')).toBeHidden();
    await expect(page.getByRole('checkbox', { name: 'Verify the backup before proceeding' })).toBeVisible();
    for (const selector of ['.rich-claim-card', '.rich-claim-card header', '.rich-claim-sources']) {
      for (const node of await page.locator(selector).all()) {
        expect(await node.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      }
    }
    const table = await page.locator('.markdown-table-wrap').boundingBox();
    const body = await page.locator('.rich-body').boundingBox();
    expect(table!.width).toBeCloseTo(body!.width, 0);
    if (width === 1440) expect((await page.locator('.rich-markdown > p').boundingBox())!.width).toBeLessThan(table!.width);
    await page.screenshot({ path: `/tmp/rich-rendering-gaps-${width}.png`, fullPage: true });
  });
}
