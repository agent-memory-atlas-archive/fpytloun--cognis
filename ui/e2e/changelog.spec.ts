import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import type { Release } from '../src/lib/changelog';
import { installTaskCockpitFixture } from './task-cockpit-fixture';

const changelog: { releases: Release[] } = JSON.parse(
  readFileSync(new URL('../src/lib/generated/changelog.json', import.meta.url), 'utf8')
);

test.use({ serviceWorkers: 'block' });

// Exercise the real authenticated route, on either a compiled app or Vite.
for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
  test(`release comparison at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await installTaskCockpitFixture(page);
    await page.route('**/api/auth/me', (route) => route.fulfill({
      json: { email: 'owner@cognis.test', role: 'user', name: 'Owner' }
    }));
    await page.route('**/api/health**', (route) => route.fulfill({ json: { status: 'ok', providers: {} } }));
    await page.routeWebSocket('**/api/ws', (socket) => {
      socket.send(JSON.stringify({ type: 'authenticated' }));
      socket.onMessage((message) => {
        if (JSON.parse(String(message)).type === 'ping') socket.send(JSON.stringify({ type: 'pong' }));
      });
    });
    const latest = changelog.releases[0];
    const previous = changelog.releases[1];
    await page.goto(`/docs/changelog?since=${previous.version}&through=${latest.version}`);

    const view = page.getByRole('main');
    await expect(view.getByRole('heading', { name: "What's new", exact: true })).toBeVisible();
    await expect(view.locator('article')).toHaveCount(1);
    await expect(view.getByRole('heading', { name: latest.version, exact: true })).toBeVisible();
    if (latest.date === 'Unreleased') {
      await expect(view.getByText('Unreleased · preview')).toBeVisible();
    }
    await expect(view.getByRole('link', { name: 'Link to this comparison' })).toHaveAttribute(
      'href', `/docs/changelog?since=${previous.version}&through=${latest.version}`
    );
    expect(await view.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`changelog-${viewport.width}.png`) });

    await view.getByLabel('Through version').selectOption(previous.version);
    await expect(view.getByRole('status')).toContainText('No releases in this range');
    await view.getByLabel('Changes after').selectOption('');
    await expect(view.getByRole('heading', { name: previous.version, exact: true })).toBeVisible();
    await expect(view.getByRole('heading', { name: latest.version, exact: true })).toHaveCount(0);
    await view.getByRole('link', { name: 'Link to this comparison' }).click();
    await expect(page).toHaveURL((url) =>
      url.pathname === '/docs/changelog' &&
      url.searchParams.get('since') === '' &&
      url.searchParams.get('through') === previous.version
    );
    await page.reload();
    await expect(view.getByRole('heading', { name: previous.version, exact: true })).toBeVisible();
  });
}
