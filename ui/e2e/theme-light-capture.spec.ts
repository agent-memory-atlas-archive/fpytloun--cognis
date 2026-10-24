import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { createServer, type ViteDevServer } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { resolve } from 'node:path';

// Local review capture only: renders production components in the shared fixture.
const directory = process.env.COGNIS_CAPTURE_DIR;
let server: ViteDevServer;
let url: string;
test.skip(!directory, 'Explicit local review capture only');
test.beforeAll(async () => {
  const sourceRoot = process.cwd();
  server = await createServer({
    configFile: false, root: sourceRoot,
    optimizeDeps: { noDiscovery: true, include: [] },
    resolve: { alias: { $lib: resolve(sourceRoot, 'src/lib') } },
    plugins: [{
      name: 'review-production-components',
      resolveId(id) { if (id.startsWith('$app/') || id.startsWith('$env/')) return `\0${id}`; },
      load(id) {
        if (id === '\0$app/environment') return 'export const browser = true; export const dev = true;';
        if (id === '\0$app/paths') return 'export const base = "";';
        if (id === '\0$app/navigation') return 'export const beforeNavigate = () => {}; export const goto = async () => {};';
        if (id.startsWith('\0$env/')) return 'export const env = {};';
      },
      configureServer(server) {
        server.middlewares.use('/review-production-components', (_req, res) => {
          res.setHeader('Content-Type', 'text/html');
          res.end('<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body><div id="fixture"></div><script type="module" src="/e2e/fixtures/theme-review/entry.ts"></script></body></html>');
        });
      },
    }, svelte()],
    server: { host: '127.0.0.1', port: 0 },
  });
  await server.listen();
  url = server.resolvedUrls!.local[0] + 'review-production-components';
});
test.afterAll(async () => { await server?.close(); });
test.use({ serviceWorkers: 'block' });

for (const family of ['classic', 'porcelain', 'paper', 'gruvbox']) {
  for (const mode of ['light', 'dark']) {
    test(`capture ${family} ${mode}`, async ({ page }) => {
      mkdirSync(directory!, { recursive: true });
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.emulateMedia({ reducedMotion: 'reduce' });
      await page.goto(`${url}?family=${family}&mode=${mode}`);
      await expect(page.locator('html')).toHaveAttribute('data-resolved-theme', mode);
      await expect(page.locator('.chat-composer-input')).toBeVisible();
      await page.screenshot({ path: `${directory}/${family}-${mode}-chat-1440.png` });
      const memory = page.locator('article').filter({ has: page.getByRole('button', { name: /memory_add/ }) }).last();
      await memory.getByRole('button', { name: /memory_add/ }).click();
      await memory.scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${directory}/${family}-${mode}-tools-1440.png` });
      const managed = page.getByRole('button', { name: /agent_conversation_interrupt/ });
      await managed.click();
      await managed.scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${directory}/${family}-${mode}-expanded-group-1440.png` });
      await page.getByTestId('attention-action-renderer').scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${directory}/${family}-${mode}-question-1440.png` });
      await page.locator('[data-message-role="user"]').first().scrollIntoViewIfNeeded();
      await page.setViewportSize({ width: 390, height: 844 });
      await page.screenshot({ path: `${directory}/${family}-${mode}-chat-390.png` });
    });
  }
}
