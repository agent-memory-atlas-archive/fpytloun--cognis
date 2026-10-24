import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createEffectiveToolsPreviewScheduler } from './effective-tools-preview';

describe('createEffectiveToolsPreviewScheduler', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not refetch an identical payload after its result is applied', async () => {
    const fetch = vi.fn(async (payload: { tools: string[] }) => payload.tools);
    const onResult = vi.fn();
    const scheduler = createEffectiveToolsPreviewScheduler({ fetch, onResult });

    scheduler.schedule({ tools: ['a'] });
    await vi.advanceTimersByTimeAsync(200);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(onResult).toHaveBeenCalledTimes(1);

    // Re-render after the result writes an equal payload back into the form.
    for (let i = 0; i < 10; i += 1) {
      scheduler.schedule({ tools: ['a'] });
      await vi.advanceTimersByTimeAsync(200);
    }
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('skips the payload already loaded through prime', async () => {
    const fetch = vi.fn(async () => 'ok');
    const scheduler = createEffectiveToolsPreviewScheduler({ fetch, onResult: vi.fn() });

    scheduler.prime({ tools: ['a'] });
    scheduler.schedule({ tools: ['a'] });
    await vi.advanceTimersByTimeAsync(500);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('aborts the in-flight request when a newer payload is sent', async () => {
    const signals: AbortSignal[] = [];
    const resolvers: Array<(value: string) => void> = [];
    const fetch = vi.fn(
      (_payload: { v: number }, signal: AbortSignal) =>
        new Promise<string>((resolve) => {
          signals.push(signal);
          resolvers.push(resolve);
        })
    );
    const onResult = vi.fn();
    const scheduler = createEffectiveToolsPreviewScheduler({ fetch, onResult });

    scheduler.schedule({ v: 1 });
    await vi.advanceTimersByTimeAsync(200);
    scheduler.schedule({ v: 2 });
    await vi.advanceTimersByTimeAsync(200);

    expect(fetch).toHaveBeenCalledTimes(2);
    expect(signals[0].aborted).toBe(true);
    expect(signals[1].aborted).toBe(false);

    resolvers[0]('stale');
    resolvers[1]('fresh');
    await vi.advanceTimersByTimeAsync(0);
    expect(onResult).toHaveBeenCalledTimes(1);
    expect(onResult).toHaveBeenCalledWith('fresh');
  });

  it('debounces rapid changes into one request', async () => {
    const fetch = vi.fn(async (_payload: { v: number }) => 'ok');
    const scheduler = createEffectiveToolsPreviewScheduler({ fetch, onResult: vi.fn() });

    for (let v = 0; v < 5; v += 1) scheduler.schedule({ v });
    await vi.advanceTimersByTimeAsync(200);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toEqual({ v: 4 });
  });

  it('allows retrying a payload after a failed request', async () => {
    const fetch = vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValue('ok');
    const scheduler = createEffectiveToolsPreviewScheduler({ fetch, onResult: vi.fn() });

    scheduler.schedule({ v: 1 });
    await vi.advanceTimersByTimeAsync(200);
    scheduler.schedule({ v: 1 });
    await vi.advanceTimersByTimeAsync(200);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('dispose aborts in-flight work and drops its result', async () => {
    let signal: AbortSignal | undefined;
    let resolve: ((value: string) => void) | undefined;
    const fetch = vi.fn(
      (_payload: unknown, s: AbortSignal) =>
        new Promise<string>((r) => {
          signal = s;
          resolve = r;
        })
    );
    const onResult = vi.fn();
    const scheduler = createEffectiveToolsPreviewScheduler({ fetch, onResult });

    scheduler.schedule({ v: 1 });
    await vi.advanceTimersByTimeAsync(200);
    scheduler.dispose();
    resolve?.('late');
    await vi.advanceTimersByTimeAsync(0);
    expect(signal?.aborted).toBe(true);
    expect(onResult).not.toHaveBeenCalled();
  });
});
