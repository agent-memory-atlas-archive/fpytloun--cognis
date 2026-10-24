import { afterEach, describe, expect, it, vi } from 'vitest';
import { QuietRefresh, REFRESH_STALE_AFTER_MS } from './quiet-refresh';

afterEach(() => vi.useRealTimers());

describe('quiet refresh freshness', () => {
  it('keeps transient failures silent and cancels on recovery', async () => {
    vi.useFakeTimers();
    const changed = vi.fn();
    const status = new QuietRefresh(changed);
    status.update('chat', true);
    await vi.advanceTimersByTimeAsync(REFRESH_STALE_AFTER_MS - 1);
    expect(changed).not.toHaveBeenCalled();
    status.update('chat', false);
    await vi.advanceTimersByTimeAsync(REFRESH_STALE_AFTER_MS);
    expect(changed).not.toHaveBeenCalled();
    status.dispose();
  });

  it('does not reset the failure interval on retries or blink while retrying', async () => {
    vi.useFakeTimers();
    const changed = vi.fn();
    const status = new QuietRefresh(changed);
    status.update('chat', true);
    await vi.advanceTimersByTimeAsync(30_000);
    status.update('chat', true);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(changed.mock.calls).toEqual([[true]]);
    status.update('chat', true);
    expect(changed.mock.calls).toEqual([[true]]);
    status.update('chat', false);
    expect(changed.mock.calls).toEqual([[true], [false]]);
  });

  it('resets across scopes and cancels timers on disposal', async () => {
    vi.useFakeTimers();
    const changed = vi.fn();
    const status = new QuietRefresh(changed);
    status.update('owner-a', true);
    await vi.advanceTimersByTimeAsync(30_000);
    status.update('owner-b', true);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(changed).not.toHaveBeenCalled();
    status.dispose();
    await vi.advanceTimersByTimeAsync(REFRESH_STALE_AFTER_MS);
    expect(changed).not.toHaveBeenCalled();
  });
});
