import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ConversationPreloadScheduler, type PreloadEnvironment } from './preload-scheduler';

function env(overrides: Partial<Record<'online' | 'visible' | 'constrained', boolean>> = {}): PreloadEnvironment {
  return {
    online: () => overrides.online ?? true,
    visible: () => overrides.visible ?? true,
    constrained: () => overrides.constrained ?? false,
    now: () => Date.now(),
  };
}

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((res) => { resolve = res; });
  return { promise, resolve };
}

async function flush(): Promise<void> {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

describe('ConversationPreloadScheduler', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('runs at most `concurrency` preloads and prioritizes activity over idle', async () => {
    const gates = new Map<string, ReturnType<typeof deferred>>();
    const started: string[] = [];
    const scheduler = new ConversationPreloadScheduler(async (id) => {
      started.push(id);
      const gate = deferred();
      gates.set(id, gate);
      await gate.promise;
    }, { concurrency: 2, environment: env() });

    scheduler.request('idle-1', { priority: 'idle' });
    scheduler.request('idle-2', { priority: 'idle' });
    scheduler.request('idle-3', { priority: 'idle' });
    scheduler.request('hot', { priority: 'activity' });
    expect(started).toEqual(['idle-1', 'idle-2']);

    gates.get('idle-1')!.resolve();
    await flush();
    expect(started).toEqual(['idle-1', 'idle-2', 'hot']);
    scheduler.dispose();
  });

  it('rate-limits a conversation and coalesces repeated requests', async () => {
    const preload = vi.fn(async () => undefined);
    const scheduler = new ConversationPreloadScheduler(preload, { minIntervalMs: 5_000, environment: env() });
    scheduler.request('a');
    await flush();
    scheduler.request('a');
    scheduler.request('a');
    await flush();
    expect(preload).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(5_000);
    await flush();
    expect(preload).toHaveBeenCalledTimes(2);
    scheduler.dispose();
  });

  it('uses a longer interval for running turns', async () => {
    const preload = vi.fn(async () => undefined);
    const scheduler = new ConversationPreloadScheduler(preload, {
      minIntervalMs: 1_000,
      activeTurnIntervalMs: 10_000,
      environment: env(),
    });
    scheduler.request('a', { activeTurn: true });
    await flush();
    scheduler.request('a', { activeTurn: true });
    vi.advanceTimersByTime(5_000);
    await flush();
    expect(preload).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(5_000);
    await flush();
    expect(preload).toHaveBeenCalledTimes(2);
    scheduler.dispose();
  });

  it('skips while offline or hidden, and idle preloads on data saver', async () => {
    const preload = vi.fn(async () => undefined);
    new ConversationPreloadScheduler(preload, { environment: env({ online: false }) }).request('a');
    new ConversationPreloadScheduler(preload, { environment: env({ visible: false }) }).request('a');
    new ConversationPreloadScheduler(preload, { environment: env({ constrained: true }) }).request('a', { priority: 'idle' });
    await flush();
    expect(preload).not.toHaveBeenCalled();
    new ConversationPreloadScheduler(preload, { environment: env({ constrained: true }) }).request('a', { priority: 'activity' });
    await flush();
    expect(preload).toHaveBeenCalledTimes(1);
  });

  it('never preloads the open conversation and aborts it when it is opened', async () => {
    let signal: AbortSignal | null = null;
    const scheduler = new ConversationPreloadScheduler(async (_id, s) => {
      signal = s;
      await new Promise(() => undefined);
    }, { environment: env() });
    scheduler.request('a');
    await flush();
    scheduler.setExcluded('a');
    expect((signal as AbortSignal | null)?.aborted).toBe(true);
    scheduler.request('a');
    expect(scheduler.pendingCount).toBe(0);
    scheduler.dispose();
  });
});
