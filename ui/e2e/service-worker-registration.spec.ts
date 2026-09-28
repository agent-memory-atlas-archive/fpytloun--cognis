import { test, expect } from '@playwright/test';
import { login } from './helpers';

test('one module-worker owner retains control across reloads', async ({ page }) => {
  await page.addInitScript(() => {
    const calls: Array<{ url: string; type: string }> = [];
    Object.assign(window, { __workerRegistrations: calls });
    const register = ServiceWorkerContainer.prototype.register;
    ServiceWorkerContainer.prototype.register = function(url, options) {
      calls.push({ url: String(url), type: options?.type ?? 'classic' });
      return register.call(this, url, options);
    };
  });
  await login(page);
  for (let i = 0; i < 3; i++) {
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller));
    // An existing controller precedes hydration and this document's registration.
    await expect.poll(() => page.evaluate(() =>
      (window as unknown as { __workerRegistrations: unknown[] }).__workerRegistrations))
      .toEqual([{ url: '/service-worker.js', type: 'module' }]);
    expect(await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.ready;
      return { active: registration.active?.state, installing: Boolean(registration.installing) };
    })).toEqual({ active: 'activated', installing: false });
  }
  await page.context().setOffline(true);
  const offlineResponse = await page.reload({ waitUntil: 'domcontentloaded' });
  expect(offlineResponse?.status()).toBe(200);
  await expect.poll(() => page.evaluate(() =>
    (window as unknown as { __workerRegistrations: unknown[] }).__workerRegistrations))
    .toEqual([{ url: '/service-worker.js', type: 'module' }]);
  expect(await page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);
});
