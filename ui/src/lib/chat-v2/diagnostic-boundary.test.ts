import { expect, it, vi } from 'vitest';
import { bounded, cleanupIndependently } from '../../../e2e/diagnostic-boundary';

it('fails with named boundary and never resolves a missing prerequisite', async () => {
  vi.useFakeTimers();
  try {
    const outcome = bounded('admission captured', new Promise<void>(() => {}));
    const assertion = expect(outcome).rejects.toThrow('Fixture boundary timed out: admission captured');
    await vi.advanceTimersByTimeAsync(10_000);
    await assertion;
    expect(vi.getTimerCount()).toBe(0);
  } finally {
    vi.useRealTimers();
  }
});

it('attempts every cleanup independently and preserves original error identity', async () => {
  const primary = new Error('original await failed');
  const secondary = new Error('context close failed');
  const last = vi.fn(async () => {});
  let observed: unknown;
  let cleanup: unknown[] = [];
  try {
    try { throw primary; }
    finally {
      cleanup = await cleanupIndependently([
        async () => { throw secondary; },
        last,
      ]);
    }
  } catch (error) { observed = error; }
  expect(observed).toBe(primary);
  expect(cleanup).toEqual([secondary]);
  expect(last).toHaveBeenCalledOnce();
});
