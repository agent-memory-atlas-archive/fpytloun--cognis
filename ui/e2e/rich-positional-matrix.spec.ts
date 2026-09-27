import { readFileSync } from 'node:fs';
import { basename, resolve } from 'node:path';
import { expect, test } from '@playwright/test';

const build = resolve('standalone-build');
const entry = JSON.parse(readFileSync(resolve(build, '.vite/manifest.json'), 'utf8'))['src/standalone.ts'];

const fixture = {
  title: 'Weekly workload audit',
  content: '',
  instanceId: '',
  payload: {
    blocks: [
      {
        type: 'comparison_matrix',
        title: 'Approval-gated findings requiring a decision',
        columns: ['Severity', 'Component', 'Exposure', 'Status', 'Recommended action'],
        rows: [
          {
            label: 'Upgrade A',
            values: ['HIGH', 'ArgoCD', 'Public', 'Staged upgrade needed', 'Approve one step only'],
          },
          {
            label: 'Upgrade B',
            values: ['MEDIUM', 'Harbor', 'Public', 'Backup gate', 'Back up database first'],
          },
        ],
      },
      {
        type: 'key_value',
        variant: 'summary',
        title: 'Coverage reconciliation',
        items: [
          { label: 'Deployed controller objects', value: '104 across 48 apps' },
          { label: 'Public hostnames', value: '28 hostnames' },
        ],
      },
    ],
  },
};

for (const width of [390, 1440]) {
  test(`positional matrix cells and summary heading at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route('**/standalone-assets/assets/*', route => {
      const filename = basename(new URL(route.request().url()).pathname);
      return route.fulfill({
        body: readFileSync(resolve(build, 'assets', filename)),
        contentType: filename.endsWith('.css') ? 'text/css' : filename.endsWith('.woff2') ? 'font/woff2' : 'text/javascript',
      });
    });
    await page.route('**/positional-matrix', route => route.fulfill({
      contentType: 'text/html',
      body: `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">${entry.css.map((file: string) => `<link rel="stylesheet" href="/standalone-assets/${file}">`).join('')}</head><body><div id="cognis-deliverable-root"></div><template id="cognis-deliverable-payload">${JSON.stringify(fixture)}</template><script type="module" src="/standalone-assets/${entry.file}"></script></body></html>`,
    }));

    await page.goto('/positional-matrix');
    const cells = page.locator('.rich-decision-matrix tbody tr:first-child td');
    await expect(cells).toHaveText(['HIGH', 'ArgoCD', 'Public', 'Staged upgrade needed', 'Approve one step only']);
    const summary = page.locator('.rich-kv-summary');
    const heading = summary.locator(':scope > h4');
    await expect(heading).toHaveText('Coverage reconciliation');
    const cardBox = await summary.boundingBox();
    const headingBox = await heading.boundingBox();
    const headingPadding = await heading.evaluate(node => parseFloat(getComputedStyle(node).paddingLeft));
    expect(headingPadding).toBeGreaterThanOrEqual(16);
    const labelBox = await summary.locator('dt').first().boundingBox();
    expect(headingBox!.x - cardBox!.x).toBeGreaterThanOrEqual(0);
    expect(headingBox!.x - cardBox!.x).toBeLessThan(2);
    expect(Math.abs(labelBox!.x - (headingBox!.x + headingPadding))).toBeLessThan(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.screenshot({ path: `/tmp/rich-positional-matrix-${width}.png`, fullPage: true });
  });
}
