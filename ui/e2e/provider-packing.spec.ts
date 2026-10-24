import { expect, test } from '@playwright/test';
import { installTaskCockpitFixture } from './task-cockpit-fixture';

for (const width of [390, 1440]) {
  test(`packs mixed provider reports into readable columns at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => {
      localStorage.setItem('cognis.dashboardHealth.selected', 'providers');
      localStorage.setItem('cognis.dashboardHealth.collapsed', 'false');
    });
    await installTaskCockpitFixture(page);
    await page.route('**/api/auth/me', (route) => route.fulfill({
      json: { email: 'owner@cognis.test', name: 'Owner', role: 'admin' }
    }));
    await page.route('**/api/health**', (route) => route.fulfill({ json: { status: 'ok', providers: {} } }));
    await page.routeWebSocket('**/api/ws', (socket) => {
      socket.send(JSON.stringify({ type: 'authenticated' }));
      socket.onMessage((message) => {
        if (JSON.parse(String(message)).type === 'ping') socket.send(JSON.stringify({ type: 'pong' }));
      });
    });
    const now = new Date().toISOString();
    const providers = [
      ['anthropic', 3], ['codex', 1], ['gemini', 0], ['groq', 0],
      ['ollama', 0], ['openai', 0], ['openrouter', 0]
    ].map(([id, count]) => ({
      provider_id: id, display_name: id,
      monitoring: { enabled: true, interval_minutes: 15, warning_percent: 20, critical_percent: 0 },
      health_status: 'healthy', health_detail: 'Available', checked_at: now, health_checked_at: now,
      next_refresh_at: null, error: null, alert_severity: null, stale: false,
      usage: count ? {
        ok: true, provider_id: id, source: 'subscription', fetched_at: now,
        primary: { used_percent: 25, window_duration_mins: 10080, resets_at: '2026-11-01T12:00:00Z' },
        secondary: count === 3 ? { used_percent: 50, window_duration_mins: 300 } : null,
        additional_rate_limits: count === 3 ? [{ limit_name: 'Sonnet', primary: { used_percent: 30 } }] : []
      } : null
    }));
    await page.route('**/api/v1/provider-monitor**', async (route) => {
      const id = new URL(route.request().url()).pathname.split('/')[4];
      await route.fulfill({ json: id ? providers.find((provider) => provider.provider_id === id) : providers });
    });
    await page.goto('/');
    await expect(page.getByRole('tab', { name: /Providers/ })).toHaveAttribute('aria-selected', 'true');
    const cards = page.getByTestId('provider-card');
    await expect(cards).toHaveCount(3);
    await expect(cards.nth(0).getByRole('progressbar')).toHaveCount(3);
    await expect(cards.nth(1).getByRole('progressbar')).toHaveCount(1);
    await expect(cards.nth(1).getByRole('link', { name: 'gemini', exact: true })).toHaveCount(1);
    await expect(cards.nth(2).getByRole('link')).toHaveCount(4);

    if (width < 640) {
      await page.getByRole('button', { name: 'Next provider card' }).click();
      await expect.poll(async () => {
        const card = await cards.nth(1).boundingBox();
        const scroller = await page.getByTestId('provider-card-scroller').boundingBox();
        return Math.abs(card!.x - scroller!.x);
      }).toBeLessThan(2);
      await expect(cards.nth(1).getByRole('button', { name: 'Refresh gemini' })).toBeInViewport();
      await page.getByRole('button', { name: 'Next provider card' }).click();
      await expect(cards.nth(2).getByRole('button', { name: 'Refresh openrouter' })).toBeInViewport();
    } else {
      const codex = await page.getByTestId('provider-health-codex').boundingBox();
      const gemini = await page.getByTestId('provider-health-gemini').boundingBox();
      expect(gemini!.y).toBeGreaterThanOrEqual(codex!.y + codex!.height);
      expect(gemini!.x).toBe(codex!.x);
      const scroller = page.getByTestId('provider-card-scroller');
      expect(await scroller.evaluate((node) => node.scrollWidth)).toBeLessThanOrEqual(await scroller.evaluate((node) => node.clientWidth));
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: test.info().outputPath(`provider-packing-${width}.png`) });
  });
}
