import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  __resetReachabilityForTests,
  __setReachabilityProbeForTests,
  isConnectivityError,
  onServerRestored,
  reportRequestFailure,
  reportRequestSuccess,
  serverReachability,
} from './server-reachability';

const timeout = Object.assign(new Error('Request timed out after 30 seconds.'), { code: 'request_timeout', status: 0 });

describe('isConnectivityError', () => {
  it('classifies network-level failures only', () => {
    expect(isConnectivityError(new TypeError('Failed to fetch'))).toBe(true);
    expect(isConnectivityError(timeout)).toBe(true);
    for (const status of [0, 502, 503, 504]) expect(isConnectivityError({ status })).toBe(true);
    expect(isConnectivityError({ status: 404 })).toBe(false);
    expect(isConnectivityError({ status: 500 })).toBe(false);
    expect(isConnectivityError(new DOMException('aborted', 'AbortError'))).toBe(false);
    expect(isConnectivityError({ status: 503, code: 'event_store_unavailable' })).toBe(false);
  });
});

describe('server reachability', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    __resetReachabilityForTests();
  });
  afterEach(() => {
    __setReachabilityProbeForTests(null);
    __resetReachabilityForTests();
    vi.useRealTimers();
  });

  it('confirms an outage with the probe, retries with backoff and reports restoration', async () => {
    const results: Array<'ok' | 'unreachable'> = ['unreachable', 'unreachable', 'ok'];
    const probe = vi.fn(async () => results.shift() ?? 'ok');
    __setReachabilityProbeForTests(probe);
    const restored = vi.fn();
    const stop = onServerRestored(restored);

    expect(reportRequestFailure(new TypeError('Failed to fetch'))).toBe(true);
    await vi.advanceTimersByTimeAsync(0);
    expect(get(serverReachability).state).toBe('unreachable');
    expect(get(serverReachability).lastFailure).toBe('Failed to fetch');

    await vi.advanceTimersByTimeAsync(2_000);
    expect(probe).toHaveBeenCalledTimes(2);
    expect(restored).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(4_000);
    expect(probe).toHaveBeenCalledTimes(3);
    expect(get(serverReachability)).toEqual({ state: 'ok', lastFailure: null });
    expect(restored).toHaveBeenCalledTimes(1);
    stop();
  });

  it('treats a timeout against a healthy server as a slow endpoint, not an outage', async () => {
    __setReachabilityProbeForTests(async () => 'ok');
    const restored = vi.fn();
    const stop = onServerRestored(restored);

    reportRequestFailure(timeout);
    await vi.advanceTimersByTimeAsync(0);

    expect(get(serverReachability).state).toBe('ok');
    expect(restored).not.toHaveBeenCalled();
    stop();
  });

  it('reports a restarting server once readiness confirms it and recovers on the next successful request', async () => {
    const probe = vi.fn(async () => 'restarting' as const);
    __setReachabilityProbeForTests(probe);
    reportRequestFailure({ status: 503 });
    expect(get(serverReachability).state).toBe('ok');
    await vi.advanceTimersByTimeAsync(0);
    expect(get(serverReachability).state).toBe('restarting');

    probe.mockResolvedValue('ok' as never);
    reportRequestSuccess();
    await vi.advanceTimersByTimeAsync(0);
    expect(get(serverReachability).state).toBe('ok');
  });

  it('does not start a restore/retry cycle for an endpoint 503 while the server is ready', async () => {
    __setReachabilityProbeForTests(async () => 'ok');
    const restored = vi.fn();
    const stop = onServerRestored(restored);
    for (let attempt = 0; attempt < 3; attempt += 1) {
      reportRequestFailure({ status: 503 });
      await vi.advanceTimersByTimeAsync(0);
    }
    expect(get(serverReachability).state).toBe('ok');
    expect(restored).not.toHaveBeenCalled();
    // Critical application 503s are not connectivity at all.
    expect(reportRequestFailure({ status: 503, code: 'event_store_unavailable' })).toBe(false);
    stop();
  });

  it('ignores real errors and caller cancellations', async () => {
    const probe = vi.fn(async () => 'ok' as const);
    __setReachabilityProbeForTests(probe);
    expect(reportRequestFailure({ status: 404 })).toBe(false);
    expect(reportRequestFailure(new DOMException('aborted', 'AbortError'))).toBe(false);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(probe).not.toHaveBeenCalled();
  });
});
