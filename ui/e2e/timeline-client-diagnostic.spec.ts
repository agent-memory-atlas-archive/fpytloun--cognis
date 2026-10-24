import { expect, test } from '@playwright/test';
type DiagnosticWindow = typeof window & {
  diagnostic: {
    events: Array<{ event: string; ms: number }>;
    subscriptions: number;
    acquired: number;
    released: number;
    snapshot: number;
    sync: number;
    pendingCancelled: number;
    releasePending(): void;
    invalidateOwner(): void;
    close(): void;
  };
};
test.use({ viewport: { width: 393, height: 852 } });
test.afterEach(async ({ page }) => {
  const current = await page.evaluate(() => (window as DiagnosticWindow).diagnostic);
  if (current) {
    await page.evaluate(() => (window as DiagnosticWindow).diagnostic.close());
    await expect.poll(() => page.evaluate(() => (window as DiagnosticWindow).diagnostic.subscriptions)).toBe(0);
  }
});

for (const surface of ['dashboard', 'tray']) {
  for (const mode of ['normal', 'blocked-cache', 'blocked-idb', 'missing-idb', 'warm', 'owner-change', 'network', 'coordination']) {
    test(`${surface} ${mode}`, async ({ page }, testInfo) => {
      // All supported API responses are in-memory injected fixture transport.
      // Block unexpected HTTP API access, including any root-layout bootstrap.
      await page.route(url => url.pathname.startsWith('/api/'), route => route.abort());
      await page.goto(`/?surface=${surface}&mode=${mode}&pending=delay`);
      if (mode === 'missing-idb') {
        await expect(page.getByRole('alert').first()).toBeVisible({ timeout: 5000 });
        await expect(page.getByText('Loading timeline…', { exact: true })).toHaveCount(0);
        console.info(JSON.stringify({ surface, mode, alerts: await page.getByRole('alert').allTextContents(),
          diagnostic: await page.evaluate(() => (window as DiagnosticWindow).diagnostic) }));
        return;
      }
      await page.getByTestId('pending-interactions-loading').waitFor();
      if (mode !== 'warm') await expect(page.getByText('Loading timeline…', { exact: true })).toBeVisible();
      if (mode === 'owner-change') await page.screenshot({ path: testInfo.outputPath('pending.png') });
      await page.evaluate(() => (window as DiagnosticWindow).diagnostic.releasePending());
      if (mode !== 'coordination') await expect(page.getByTestId('pending-interactions-loading')).toHaveCount(0, { timeout: 5000 });
      if (mode === 'owner-change') {
        // Exact two-stage mobile regression: banner settles independently,
        // while timeline hydration is still waiting before any snapshot/WS.
        await expect(page.getByText('Loading timeline…', { exact: true })).toBeVisible();
        await page.evaluate(() => (window as DiagnosticWindow).diagnostic.invalidateOwner());
        await expect(page.getByText('Loading timeline…', { exact: true })).toHaveCount(0);
        await expect(page.getByRole('alert')).toContainText('Verify your session');
        await page.screenshot({ path: testInfo.outputPath('identity.png') });
      }
      if (mode === 'owner-change' || mode === 'coordination' || mode === 'network') {
        await page.waitForTimeout(17_000);
        console.info(JSON.stringify({ surface, mode, timelineLoading: await page.getByText('Loading timeline…', { exact: true }).count(),
          alerts: await page.getByRole('alert').allTextContents(), diagnostic: await page.evaluate(() => (window as DiagnosticWindow).diagnostic) }));
        // Retained failing invariant: current owner loss cannot leave the
        // initial pre-network spinner alive indefinitely.
        await expect(page.getByText('Loading timeline…', { exact: true })).toHaveCount(0);
        if (mode === 'owner-change') {
          await expect(page.getByRole('alert')).toContainText('Verify your session');
          expect(await page.evaluate(() => (window as DiagnosticWindow).diagnostic.snapshot)).toBe(0);
          expect(await page.evaluate(() => (window as DiagnosticWindow).diagnostic.acquired)).toBe(0);
        } else {
          // Existing connectivity precedence hides section errors during an
          // outage. It must still leave loading and expose its settled state.
          await expect(page.getByText('Timeline unavailable. Waiting for connection.')).toBeVisible();
          expect(await page.evaluate(() => (window as DiagnosticWindow).diagnostic.snapshot)).toBe(mode === 'network' ? 1 : 0);
          expect(await page.evaluate(() => (window as DiagnosticWindow).diagnostic.acquired)).toBe(0);
        }
      } else {
        await expect(page.getByText('Synthetic timeline ready')).toBeVisible({ timeout: 5000 });
        console.info(JSON.stringify({ surface, mode, diagnostic: await page.evaluate(() => (window as DiagnosticWindow).diagnostic) }));
      }
    });
  }
}
for (const pending of ['fail', 'body', 'error-body']) {
  test(`dashboard pending ${pending} never gates timeline`, async ({ page }) => {
    await page.route(url => url.pathname.startsWith('/api/'), route => route.abort());
    await page.goto(`/?surface=dashboard&mode=normal&pending=${pending}`);
    await expect(page.getByText('Synthetic timeline ready')).toBeVisible({ timeout: 10000 });
    await page.evaluate(() => (window as DiagnosticWindow).diagnostic.releasePending());
    if (pending === 'body' || pending === 'error-body') {
      // Preserve the general client's supported 30s default, including body
      // decoding. The prior diagnostic deliberately observed the missing bound.
      await expect(page.getByTestId('pending-interactions-loading')).toHaveCount(0, { timeout: 35_000 });
      console.info(JSON.stringify({ pending, bannerStillLoading: await page.getByTestId('pending-interactions-loading').count(),
        diagnostic: await page.evaluate(() => (window as DiagnosticWindow).diagnostic) }));
      await expect(page.getByTestId('pending-interactions-loading')).toHaveCount(0);
      await expect(page.getByRole('alert')).toContainText('timed out');
      expect(await page.evaluate(() => (window as DiagnosticWindow).diagnostic.pendingCancelled)).toBe(1);
    } else await expect(page.getByRole('alert')).toContainText('Synthetic pending failure');
  });
}
for (const surface of ['dashboard', 'tray']) {
  test(`${surface} subscription lifetime`, async ({ page }) => {
    await page.route(url => url.pathname.startsWith('/api/'), route => route.abort());
    await page.goto(`/?surface=${surface}&mode=normal&pending=delay`);
    await expect(page.getByText('Synthetic timeline ready')).toBeVisible();
    const before = await page.evaluate(() => {
      const state = (window as DiagnosticWindow).diagnostic;
      state.releasePending();
      return { subscriptions: state.subscriptions, acquired: state.acquired };
    });
    await page.evaluate(() => (window as DiagnosticWindow).diagnostic.close());
    await expect.poll(() => page.evaluate(() => (window as DiagnosticWindow).diagnostic.released)).toBe(1);
    const after = await page.evaluate(() => ({
      subscriptions: (window as DiagnosticWindow).diagnostic.subscriptions,
      released: (window as DiagnosticWindow).diagnostic.released,
    }));
    expect(before.acquired).toBe(1);
    expect(after.subscriptions).toBeLessThan(before.subscriptions);
    console.info(JSON.stringify({ surface, lifetime: { before, after } }));
  });
}
