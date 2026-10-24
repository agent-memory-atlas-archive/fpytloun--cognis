import { expect, test } from '@playwright/test';

type AuditWindow = typeof window & {
  historyFixture: {
    nextSnapshots: number;
    snapshotAborts: number;
    syncRequests: number;
    releaseSync: (() => void) | null;
    releaseSnapshot: (() => void) | null;
    preloadNext(): void;
    append(): void;
    changeConversation(): void;
    returnConversation(): void;
    unexpectedRequests: string[];
  };
  pendingIdlePreloads(): number;
  runIdlePreloads(): void;
};

test('idle preload cannot replace the selected chat, its reading position, or its live subscription', async ({ page }) => {
  await page.addInitScript(() => {
    const callbacks: IdleRequestCallback[] = [];
    window.requestIdleCallback = callback => { callbacks.push(callback); return callbacks.length; };
    Object.assign(window, {
      pendingIdlePreloads: () => callbacks.length,
      runIdlePreloads: () => {
        for (const callback of callbacks.splice(0)) {
          callback({ didTimeout: false, timeRemaining: () => 50 });
        }
      },
    });
  });
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.goto('/history.html?audit-preloads');
  const full = page.getByTestId('full-surface');
  const viewport = full.getByTestId('timeline-viewport');
  await expect(full.getByRole('link', { name: /Next conversation/ })).toBeAttached();
  await page.waitForFunction(() => (window as AuditWindow).pendingIdlePreloads() > 0);
  await expect(viewport.getByText('Synthetic history 199', { exact: true })).toBeAttached();
  await expect.poll(() => viewport.evaluate(v => v.scrollHeight - v.scrollTop - v.clientHeight)).toBeLessThanOrEqual(2);
  await viewport.evaluate(v => {
    v.dispatchEvent(new WheelEvent('wheel', { deltaY: -1 }));
    v.scrollTop -= 400;
  });
  await expect(viewport.getByRole('button', { name: 'Scroll to bottom', exact: true })).toBeAttached();
  const before = await viewport.evaluate(v => ({
    top: v.scrollTop,
    keys: [...v.querySelectorAll<HTMLElement>('[data-timeline-row-key]')].map(row => row.dataset.timelineRowKey),
  }));
  await page.evaluate(() => (window as AuditWindow).runIdlePreloads());
  await page.waitForFunction(() => (window as AuditWindow).historyFixture.nextSnapshots === 1);
  await viewport.evaluate(async () => {
    await new Promise(requestAnimationFrame);
    await new Promise(requestAnimationFrame);
  });
  await expect(viewport.getByText('New conversation only', { exact: true })).not.toBeAttached();
  expect(await viewport.evaluate(v => ({
    top: v.scrollTop,
    keys: [...v.querySelectorAll<HTMLElement>('[data-timeline-row-key]')].map(row => row.dataset.timelineRowKey),
  }))).toEqual(before);
  // The visible controller must still receive and project the selected chat's
  // live frames after the unrelated chat has been warmed.
  await page.evaluate(() => (window as AuditWindow).historyFixture.append());
  await expect(viewport.getByText('Synthetic live update 1', { exact: true })).toBeAttached();
  await page.evaluate(() => (window as AuditWindow).historyFixture.changeConversation());
  await expect(viewport.getByText('New conversation only', { exact: true })).toBeAttached();
  await expect(viewport.getByText('Synthetic history 199', { exact: true })).not.toBeAttached();
  await page.evaluate(() => (window as AuditWindow).historyFixture.returnConversation());
  await expect(viewport.getByText('Synthetic live update 1', { exact: true })).toBeAttached();
  await expect(viewport.getByText('New conversation only', { exact: true })).not.toBeAttached();
  expect(await page.evaluate(() => (window as AuditWindow).historyFixture.unexpectedRequests)).toEqual([]);
});
test('mobile foreground refresh does not strand chat switching while catch-up is pending', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 393, height: 852 });
  await page.goto('/history.html?audit-preloads&full-only&hold-sync');
  const full = page.getByTestId('full-surface');
  const viewport = full.getByTestId('timeline-viewport');
  await expect(viewport.getByText('Synthetic history 199', { exact: true })).toBeAttached();
  await page.evaluate(() => {
    const now = Date.now.bind(Date);
    Date.now = () => now() + 8 * 60 * 60 * 1000;
    window.dispatchEvent(new Event('focus'));
  });
  await page.waitForFunction(() => (window as AuditWindow).historyFixture.releaseSync !== null);
  await page.evaluate(() => (window as AuditWindow).historyFixture.changeConversation());
  await expect(viewport.getByText('New conversation only', { exact: true })).toBeAttached();
  await page.evaluate(() => (window as AuditWindow).historyFixture.returnConversation());
  await expect(viewport.getByText('Synthetic history 199', { exact: true })).toBeAttached();
  await page.evaluate(() => (window as AuditWindow).historyFixture.releaseSync?.());
  await expect(full.getByText('Loading timeline…', { exact: true })).toHaveCount(0);
  await expect(full.getByRole('button', { name: 'Retry history', exact: true })).not.toBeAttached();
  await page.evaluate(() => (window as AuditWindow).historyFixture.append());
  await expect(viewport.getByText('Synthetic live update 1', { exact: true })).toBeAttached();
  expect(errors).toEqual([]);
});

test('activity preloading cannot abort the selected history while its first snapshot is loading', async ({ page }) => {
  await page.goto('/history.html?audit-preloads&hold-snapshot&full-only');
  const full = page.getByTestId('full-surface');
  const viewport = full.getByTestId('timeline-viewport');
  await expect(full.getByRole('link', { name: /Next conversation/ })).toBeAttached();
  await page.waitForFunction(() => (window as AuditWindow).historyFixture.releaseSnapshot !== null);
  await page.evaluate(() => (window as AuditWindow).historyFixture.preloadNext());
  await page.waitForFunction(() => (window as AuditWindow).historyFixture.nextSnapshots === 1);
  expect(await page.evaluate(() => (window as AuditWindow).historyFixture.snapshotAborts)).toBe(0);
  await page.evaluate(() => (window as AuditWindow).historyFixture.releaseSnapshot?.());
  await expect(viewport.getByText('Synthetic history 199', { exact: true })).toBeAttached();
  await expect(viewport.getByText('New conversation only', { exact: true })).not.toBeAttached();
  await expect(full.getByRole('button', { name: 'Retry history', exact: true })).not.toBeAttached();
  await expect(full.getByText('The operation was aborted.', { exact: true })).not.toBeAttached();
  expect(await page.evaluate(() => (window as AuditWindow).historyFixture.unexpectedRequests)).toEqual([]);
});
