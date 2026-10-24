import { afterEach, describe, expect, it, vi } from 'vitest';

import { FetchTimeoutError, fetchWithTimeout, withRequestDeadline, readJsonWithSignal, cancelResponseOnAbort } from './fetch';

describe('fetchWithTimeout', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('aborts stalled requests after the configured timeout', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn<typeof fetch>().mockImplementation((_input, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true });
    }));

    const promise = fetchWithTimeout('/api/test', {}, { fetchImpl: fetchMock, timeoutMs: 25 })
      .catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(25);

    await expect(promise).resolves.toBeInstanceOf(FetchTimeoutError);
  });

  it('rejects on timeout even when fetch ignores abort and never settles', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(() => new Promise(() => {}));

    const promise = fetchWithTimeout('/api/test', {}, { fetchImpl: fetchMock, timeoutMs: 25 })
      .catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(25);

    await expect(promise).resolves.toBeInstanceOf(FetchTimeoutError);
  });

  it('preserves caller abort signals', async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const fetchMock = vi.fn<typeof fetch>().mockImplementation((_input, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true });
    }));

    const promise = fetchWithTimeout(
      '/api/test',
      { signal: controller.signal },
      { fetchImpl: fetchMock, timeoutMs: 1_000 }
    );
    const reason = new Error('caller aborted');
    controller.abort(reason);

    await expect(promise).rejects.toBe(reason);
  });

  it('cleans deadline timers and caller listeners after success, error, and caller abort', async () => {
    vi.useFakeTimers();
    for (const outcome of ['success', 'error', 'abort', 'timeout']) {
      const caller = new AbortController();
      const added = vi.spyOn(caller.signal, 'addEventListener');
      const removed = vi.spyOn(caller.signal, 'removeEventListener');
      const promise = withRequestDeadline(async () => {
        if (outcome === 'error') throw new Error('operation failed');
        if (outcome === 'abort' || outcome === 'timeout') return new Promise(() => {});
        return 'ready';
      }, { signal: caller.signal, timeoutMs: 50 });
      const settled = promise.catch(error => error);
      if (outcome === 'abort') caller.abort();
      if (outcome === 'timeout') await vi.advanceTimersByTimeAsync(50);
      await settled;
      expect(vi.getTimerCount()).toBe(0);
      expect(removed.mock.calls.length).toBe(added.mock.calls.length);
    }
  });

  it.each(['success', 'error', 'abort'])('releases response and reader listeners after %s', async outcome => {
    const caller = new AbortController();
    const added = vi.spyOn(caller.signal, 'addEventListener');
    const removed = vi.spyOn(caller.signal, 'removeEventListener');
    const cancel = vi.fn();
    const response = new Response(new ReadableStream({
      start(controller) {
        if (outcome === 'abort') return;
        controller.enqueue(new TextEncoder().encode(outcome === 'success' ? '[]' : '{'));
        controller.close();
      },
      cancel,
    }));
    const release = cancelResponseOnAbort(response, caller.signal);
    const operation = readJsonWithSignal(response, caller.signal).catch(error => error);
    if (outcome === 'abort') caller.abort();
    const result = await operation;
    release();
    expect(response.body?.locked).toBe(false);
    expect(removed).toHaveBeenCalledTimes(added.mock.calls.length);
    for (const [type, listener] of added.mock.calls) {
      expect(removed).toHaveBeenCalledWith(type, listener);
    }
    if (outcome === 'abort') {
      expect(result).toMatchObject({ name: 'AbortError' });
      expect(cancel).toHaveBeenCalledOnce();
    } else if (outcome === 'error') expect(result).toBeInstanceOf(SyntaxError);
    else expect(result).toEqual([]);
  });

  it('retains explicit long-operation timeout opt-outs and handles already-aborted callers', async () => {
    vi.useFakeTimers();
    let complete!: () => void;
    const operation = withRequestDeadline(() => new Promise<void>(resolve => { complete = resolve; }), { timeoutMs: 0 });
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(60_000);
    complete();
    await operation;
    const caller = new AbortController();
    caller.abort();
    const notStarted = vi.fn();
    await expect(withRequestDeadline(notStarted, { signal: caller.signal })).rejects.toMatchObject({ name: 'AbortError' });
    expect(notStarted).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
});
