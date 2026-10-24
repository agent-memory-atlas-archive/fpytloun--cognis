import { readFileSync } from 'node:fs';
import { basename, resolve } from 'node:path';
import { expect, test } from '@playwright/test';

const build = resolve('standalone-build');
const entry = JSON.parse(readFileSync(resolve(build, '.vite/manifest.json'), 'utf8'))['src/standalone.ts'];
// Synthetic incident details exercise wrapping, alignment, and escaped arrows.
const payload = {
  title: 'Saturation report',
  content: '',
  instanceId: '',
  payload: {
    blocks: [
      { type: 'hero', title: 'Saturation report' },
      { type: 'key_value', variant: 'summary', items: Array.from({ length: 6 }, (_, i) => ({ label: `Metric ${i}`, value: `${i * 100}` })) },
      { type: 'markdown', content: 'A long paragraph about a measurable saturation event and its causes. '.repeat(20) },
      { type: 'timeline', title: 'How it got here', items: [
        { time: 'Day 1', title: 'Started', description: 'The first event.' },
        { time: 'Days 2–3', title: 'Continued', description: 'The second event.' },
        { time: 'Day 3 ~17:00', title: 'Exceeded threshold', description: 'The third event.' },
      ] },
      { type: 'mermaid', title: 'Request flow', source: 'flowchart LR\n A["Source"] --&gt; B["Destination"]' },
      { type: 'mermaid', title: 'Example catalog, two lookup modes', source: 'flowchart LR\n  subgraph NOW["EXAMPLE: per-file lookup"]\n    A1["240,000 sample files"] --&gt; A2["1 HEAD request\\nper file"]\n    A2 --&gt; A3["240,000 requests\\nper 20-min cycle"]\n  end\n  subgraph FIX["EXAMPLE: batch listing"]\n    B1["240,000 sample files"] --&gt; B2["paged LIST\\n1,000 keys per request"]\n    B2 --&gt; B3["240 requests\\nper 20-min cycle"]\n  end\n  A3 --&gt; R["1000x fewer requests"]\n  B3 --&gt; R' },
      { type: 'incident_timeline', title: 'How it got here', items: [
        { time: 'Day 1', title: 'Sample indexer deployed', description: 'Example cycles complete in 60–90 s.' },
        { time: 'Days 2–3', title: 'Sample import completes' },
        { time: 'Day 3 ~17:00', title: 'Threshold crossed' },
        { time: 'Day 3 ~19:00', title: 'Load steps 18 → 260' },
        { time: 'Day 4 09:30', title: 'Sample cleanup queued' },
        { time: 'Day 4 12:00', title: 'Load recovering' },
      ] },
      { type: 'steps', title: 'Remediation', items: [
        { title: '1. Reduce workers', description: 'Measure the result.' },
        { title: '2. Update traversal', description: 'Verify correctness.' },
      ] },
    ],
  },
};

for (const width of [390, 1440]) {
  test(`report layout and escaped Mermaid arrows at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route('**/standalone-assets/assets/*', route => {
      const filename = basename(new URL(route.request().url()).pathname);
      return route.fulfill({ body: readFileSync(resolve(build, 'assets', filename)), contentType: filename.endsWith('.css') ? 'text/css' : filename.endsWith('.woff2') ? 'font/woff2' : 'text/javascript' });
    });
    await page.route('**/rich-report-parity', route => route.fulfill({
      contentType: 'text/html',
      body: `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">${entry.css.map((file: string) => `<link rel="stylesheet" href="/standalone-assets/${file}">`).join('')}</head><body><div id="cognis-deliverable-root"></div><template id="cognis-deliverable-payload">${JSON.stringify(payload)}</template><script type="module" src="/standalone-assets/${entry.file}"></script></body></html>`,
    }));
    await page.goto('/rich-report-parity');
    await expect(page.locator('.rich-mermaid svg')).toHaveCount(2, { timeout: 20_000 });
    await expect(page.locator('.rich-diagram pre[data-mermaid-source]')).toHaveCount(0);
    await expect(page.locator('.rich-steps li strong').first()).toHaveText('Reduce workers');
    const metrics = await page.locator('.rich-kv-summary dl > div').all();
    expect(metrics).toHaveLength(6);
    const positions = await Promise.all(metrics.map(metric => metric.boundingBox()));
    if (width === 1440) {
      expect(positions[0]!.y).toBe(positions[2]!.y);
      expect(positions[3]!.y).toBeGreaterThan(positions[0]!.y);
      const prose = await page.locator('.rich-markdown > p').first().boundingBox();
      expect(prose!.width).toBeGreaterThan(580);
    } else {
      expect(positions[0]!.y).toBe(positions[1]!.y);
      expect(positions[2]!.y).toBeGreaterThan(positions[0]!.y);
    }
    const entries = await page.locator('.rich-timeline:not(.rich-steps) li > div').all();
    const textBoxes = await Promise.all(entries.map(item => item.boundingBox()));
    expect(new Set(textBoxes.map(box => Math.round(box!.x))).size).toBe(1);
    const incidents = await page.locator('.rich-incident-timeline li').all();
    expect(incidents).toHaveLength(6);
    const incidentPositions = await Promise.all(incidents.map(async incident => ({
      date: await incident.locator(':scope > span').boundingBox(),
      title: await incident.locator('summary strong').boundingBox(),
    })));
    expect(new Set(incidentPositions.map(({ title }) => Math.round(title!.x))).size).toBe(1);
    if (width === 1440) {
      for (const { date, title } of incidentPositions) {
        expect(Math.abs(date!.y + date!.height / 2 - (title!.y + title!.height / 2))).toBeLessThan(2);
      }
    } else {
      for (const { date, title } of incidentPositions) expect(title!.y).toBeGreaterThan(date!.y);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.emulateMedia({ media: 'print' });
    await expect(page.locator('.rich-mermaid svg')).toHaveCount(2);
    await expect(page.getByRole('heading', { name: 'Saturation report', exact: true })).toBeVisible();
    await expect(page.locator('.theme-control')).toBeHidden();
  });
}
