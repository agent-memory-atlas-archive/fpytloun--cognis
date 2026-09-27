import { readFileSync } from 'node:fs';
import { basename, resolve } from 'node:path';
import { expect, test } from '@playwright/test';

const build = resolve('standalone-build');
const entry = JSON.parse(readFileSync(resolve(build, '.vite/manifest.json'), 'utf8'))['src/standalone.ts'];
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
        { time: '22 Sep', title: 'Started', description: 'The first event.' },
        { time: '23–24 Sep', title: 'Continued', description: 'The second event.' },
        { time: '24 Sep ~18:00', title: 'Exceeded threshold', description: 'The third event.' },
      ] },
      { type: 'mermaid', title: 'Request flow', source: 'flowchart LR\n A["Source"] --&gt; B["Destination"]' },
      { type: 'mermaid', title: 'The same job, two traversal modes', source: 'flowchart LR\n  subgraph NOW["TODAY: --no-traverse"]\n    A1["816,593 source files"] --&gt; A2["1 HEAD request\\nper file"]\n    A2 --&gt; A3["~786,000 S3 requests\\nper 10-min cycle"]\n  end\n  subgraph FIX["PROPOSED: listing"]\n    B1["816,593 source files"] --&gt; B2["paged LIST\\n1,000 keys per request"]\n    B2 --&gt; B3["~786 S3 requests\\nper 10-min cycle"]\n  end\n  A3 --&gt; R["1000x fewer requests"]\n  B3 --&gt; R' },
      { type: 'incident_timeline', title: 'How it got here', items: [
        { time: '22 Sep', title: 'logs-actalign deployed', description: 'Cycles complete in 83–142 s.' },
        { time: '23–24 Sep', title: 'Backfill completes' },
        { time: '24 Sep ~18:00', title: 'Threshold crossed' },
        { time: '24 Sep ~20:00', title: 'Load steps 28 → 395' },
        { time: '25 Sep 10:26', title: 'actalign cleanup armed' },
        { time: '25 Sep 13:00', title: 'Still saturated' },
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
  });
}
