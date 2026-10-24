import 'fake-indexeddb/auto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from './client';
import { documentCoordination } from '$lib/document-coordination';
import { auth } from '$lib/stores/auth';
import { metadataReadFlights } from './read-flights';

const headers = { 'Content-Type': 'application/json' };
let validate: ReturnType<typeof vi.fn<() => Promise<void>>>;
beforeEach(async () => {
  // Explicit in-memory synthetic principal; no login endpoint or credentials.
  await documentCoordination().beginLogin();
  await documentCoordination().verified('deadline-fixture@cognis.test');
  const lease = documentCoordination().capture();
  validate = vi.fn<() => Promise<void>>(async () => lease.assertCurrent());
  vi.spyOn(documentCoordination(), 'capture').mockReturnValue({ ...lease, validate });
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('typed JSON operation deadline', () => {
  it('keeps the caller deadline across repeated metadata invalidations', async () => {
    const fetch = vi.fn((_url, options) => new Promise<Response>((_resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true });
    }));
    vi.stubGlobal('fetch', fetch);
    const pending = api.conversations.sidebar();
    const rejected = expect(pending).rejects.toMatchObject({ code: 'request_timeout', status: 0 });
    await vi.advanceTimersByTimeAsync(10_000);
    metadataReadFlights.invalidate();
    await vi.advanceTimersByTimeAsync(10_000);
    metadataReadFlights.invalidate();
    await vi.advanceTimersByTimeAsync(10_001);
    await rejected;
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([200, 503])('bounds and cancels a stalled %s body after immediate headers', async status => {
    const cancel = vi.fn();
    const fetch = vi.fn().mockResolvedValue(new Response(new ReadableStream({
      start(controller) { controller.enqueue(new TextEncoder().encode('{"fixture":')); },
      cancel,
    }), { status, headers }));
    vi.stubGlobal('fetch', fetch);
    const request = api.notifications.list('synthetic-body-deadline');
    const rejected = expect(request).rejects.toMatchObject({ code: 'request_timeout', status: 0 });
    await vi.advanceTimersByTimeAsync(30_001);
    await rejected;
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('bounds a pre-fetch lease wait and never sends after a late grant', async () => {
    let grant!: () => void;
    validate.mockImplementation(() => new Promise<void>(resolve => { grant = resolve; }));
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    const request = api.notifications.list('synthetic-coordination-deadline');
    const rejected = expect(request).rejects.toMatchObject({ code: 'request_timeout' });
    await vi.advanceTimersByTimeAsync(30_001);
    await rejected;
    grant();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('bounds post-read validation without publishing a late success', async () => {
    validate.mockImplementationOnce(async () => {}).mockImplementationOnce(async () => {})
      .mockImplementationOnce(() => new Promise<void>(() => {}));
    const fetch = vi.fn().mockResolvedValue(new Response('[]', { headers }));
    vi.stubGlobal('fetch', fetch);
    const request = api.notifications.list('synthetic-post-read-deadline');
    const rejected = expect(request).rejects.toMatchObject({ code: 'request_timeout' });
    await vi.advanceTimersByTimeAsync(30_001);
    await rejected;
    expect(validate).toHaveBeenCalledTimes(3);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('cancels its body reader on view teardown, preserving cancellation rather than timeout', async () => {
    const cancel = vi.fn();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new ReadableStream({ cancel }), { headers })));
    const view = new AbortController();
    const request = api.notifications.list('synthetic-navigation', { signal: view.signal });
    const rejected = expect(request).rejects.toMatchObject({ name: 'AbortError' });
    await vi.advanceTimersByTimeAsync(1);
    view.abort();
    await rejected;
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('cancels during a coordination wait and never sends after that lease settles', async () => {
    let grant!: () => void;
    validate.mockImplementation(() => new Promise<void>(resolve => { grant = resolve; }));
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    const view = new AbortController();
    const request = api.notifications.list('synthetic-coordination-navigation', { signal: view.signal });
    const rejected = expect(request).rejects.toMatchObject({ name: 'AbortError' });
    view.abort();
    await rejected;
    grant();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('bounds shared auth recovery without retrying a mutation after expiry', async () => {
    const cancel = vi.fn();
    const fetch = vi.fn().mockResolvedValue(new Response(new ReadableStream({ cancel }), { status: 401, headers }));
    vi.stubGlobal('fetch', fetch);
    let recover!: (result: 'valid') => void;
    vi.spyOn(auth, 'recoverSession').mockImplementation(() => new Promise(resolve => { recover = resolve; }));
    const request = api.notifications.resolve('synthetic-mutation', { decision: 'continue' });
    const rejected = expect(request).rejects.toMatchObject({ code: 'request_timeout' });
    await vi.advanceTimersByTimeAsync(30_001);
    await rejected;
    recover('valid');
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][1].method).toBe('POST');
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });
});
