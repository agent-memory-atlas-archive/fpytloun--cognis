import { readFileSync } from 'node:fs';
import { basename, resolve } from 'node:path';
import { expect, test } from '@playwright/test';

const build = resolve('standalone-build');
const entry = JSON.parse(readFileSync(resolve(build, '.vite/manifest.json'), 'utf8'))['src/standalone.ts'];
const fixture = {
  title: 'Workload review',
  content: '',
  instanceId: '',
  payload: { blocks: [
    { type: 'section', heading: 'Deployed this run', body: 'Both upgrades are live and verified.' },
    { type: 'comparison_matrix', title: 'Control-plane upgrades', columns: ['Before', 'After'], rows: [
      { label: 'Service A', values: ['v1', 'v2'] },
    ] },
    { type: 'claim_cards', title: 'Skipped before mutation', cards: [
      { claim: 'Historic document unchanged', evidence: 'Dated evidence must be preserved.', verdict: 'Correctly deferred' },
      { claim: 'Upgrade blocked', evidence: 'No established host access.', verdict: 'Blocked on tooling' },
    ] },
    { type: 'callout', variant: 'warning', text: 'Follow up in the next approved maintenance window.' },
  ] },
};

for (const width of [390, 1440]) {
  test(`workload report preserves every block at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route('**/standalone-assets/assets/*', route => {
      const file = basename(new URL(route.request().url()).pathname);
      return route.fulfill({
        body: readFileSync(resolve(build, 'assets', file)),
        contentType: file.endsWith('.css') ? 'text/css' : file.endsWith('.woff2') ? 'font/woff2' : 'text/javascript',
      });
    });
    await page.route('**/workload-content', route => route.fulfill({
      contentType: 'text/html',
      body: `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">${entry.css.map((file: string) => `<link rel="stylesheet" href="/standalone-assets/${file}">`).join('')}</head><body><div id="cognis-deliverable-root"></div><template id="cognis-deliverable-payload">${JSON.stringify(fixture)}</template><script type="module" src="/standalone-assets/${entry.file}"></script></body></html>`,
    }));
    await page.goto('/workload-content');
    await expect(page.locator('[data-rich-block-type="section"] .rich-markdown')).toContainText('Both upgrades are live and verified.');
    await expect(page.locator('[data-rich-block-type="comparison_matrix"] tbody td')).toHaveText(['v1', 'v2']);
    const claims = page.locator('[data-rich-block-type="claim_cards"] .rich-claim-card');
    await expect(claims).toHaveCount(2);
    await expect(claims.first()).toContainText('Dated evidence must be preserved.');
    await expect(claims.first()).toContainText('Correctly deferred');
    await expect(claims.nth(1)).toContainText('No established host access.');
    await expect(page.locator('[data-rich-block-type="claim_cards"] .rich-confidence')).toHaveCount(0);
    await expect(page.locator('[data-rich-block-type="callout"]')).toContainText('Follow up in the next approved maintenance window.');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.screenshot({ path: `/tmp/rich-workload-content-${width}.png`, fullPage: true });
  });
}
