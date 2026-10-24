import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { loginFixtureAccount } from '../../test/verified-account';
import { api } from './client';
import { metadataReadFlights } from './read-flights';
import { auth } from '$lib/stores/auth';
import { CognisWebSocketClient } from '$lib/ws/client';
import { RefreshCooldown, SidebarRefreshController } from '$lib/sidebar-refresh';
import { documentCoordination } from '$lib/document-coordination';

const originalFetch = globalThis.fetch;
beforeEach(loginFixtureAccount);
afterEach(async () => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  metadataReadFlights.invalidate();
  globalThis.fetch = originalFetch;
  await auth.clear();
});

function fixtureTransport() {
  const pending: Array<{ signal: AbortSignal; resolve: (value: Response) => void }> = [];
  const fetch = vi.fn((_url: unknown, options?: RequestInit) => new Promise<Response>((resolve, reject) => {
    const signal = options!.signal!;
    pending.push({ signal, resolve });
    signal.addEventListener('abort', () => reject(signal.reason), { once: true });
  }));
  globalThis.fetch = fetch;
  return { fetch, pending };
}

const response = (revision: number) => new Response(JSON.stringify({ revision }), {
  status: 200, headers: { 'Content-Type': 'application/json' },
});

it('coalesces equivalent sidebar calls at the real client boundary and keeps cancellation independent', async () => {
  const { fetch, pending } = fixtureTransport();
  const abort = new AbortController();
  const a = api.conversations.sidebar(null, {}, { signal: abort.signal });
  const b = api.conversations.sidebar();
  const filtered = api.conversations.sidebar(null, { status: 'archived' });
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  abort.abort();
  await expect(a).rejects.toHaveProperty('name', 'AbortError');
  expect(pending[0].signal.aborted).toBe(false);
  pending[0].resolve(response(1));
  pending[1].resolve(response(2));
  await expect(b).resolves.toEqual({ revision: 1 });
  await expect(filtered).resolves.toEqual({ revision: 2 });
});

it('reissues an invalidated flight once for all waiting consumers without publishing its old result', async () => {
  const { fetch, pending } = fixtureTransport();
  const a = api.conversations.sidebar();
  const b = api.conversations.sidebar();
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  const client = new CognisWebSocketClient();
  (client as unknown as { handleMessage(raw: string): void }).handleMessage(
    JSON.stringify({ type: 'scope_invalidated', reason: 'sidebar_changed' }),
  );
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  pending[0].resolve(response(1));
  pending[1].resolve(response(2));
  await expect(a).resolves.toEqual({ revision: 2 });
  await expect(b).resolves.toEqual({ revision: 2 });
  client.disconnect();
});

it('keeps one delayed sidebar transport and one trailing refresh through a realtime burst', async () => {
  // Keep account fencing real, but avoid putting IndexedDB's task queue under
  // the fake clock used to assert the sidebar's exact four-second spacing.
  const lease = documentCoordination().capture();
  vi.spyOn(documentCoordination(), 'capture').mockReturnValue({
    ...lease, validate: async () => lease.assertCurrent(),
  });
  vi.useFakeTimers();
  const { fetch, pending } = fixtureTransport();
  const client = new CognisWebSocketClient();
  const values: unknown[] = [];
  const controller = new SidebarRefreshController(async ({ signal }) => {
    values.push(await api.conversations.sidebar(null, {}, { signal }));
  }, new RefreshCooldown());
  const stop = client.subscribe(() => { void controller.request('owner/web'); });
  try {
    const first = controller.request('owner/web');
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledTimes(1);
    for (let i = 0; i < 100; i++) {
      for (const event of [
        { type: 'scope_invalidated', reason: 'executor_state_changed' },
        { type: 'scope_invalidated', reason: 'notification_state_changed' },
        { type: 'conversation_runtime_snapshot' },
        { type: 'message_complete' },
      ]) {
        (client as unknown as { handleMessage(raw: string): void }).handleMessage(JSON.stringify(event));
      }
    }
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(pending[0].signal.aborted).toBe(false);
    pending[0].resolve(response(1));
    await first;
    await vi.advanceTimersByTimeAsync(3_999);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetch).toHaveBeenCalledTimes(2);
    pending[1].resolve(response(2));
    await vi.advanceTimersByTimeAsync(0);
    expect(values).toEqual([{ revision: 1 }, { revision: 2 }]);
  } finally {
    stop();
    controller.dispose();
    client.disconnect();
  }
});

it('does not reissue or publish an old account flight after logout', async () => {
  const { fetch } = fixtureTransport();
  const result = api.conversations.sidebar();
  const rejected = expect(result).rejects.toBeDefined();
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  await auth.clear();
  await rejected;
  expect(fetch).toHaveBeenCalledTimes(1);
});

it('lets the sidebar refresh owner finish a delayed read through a work burst, then read once more', async () => {
  const lease = documentCoordination().capture();
  vi.spyOn(documentCoordination(), 'capture').mockReturnValue({
    ...lease, validate: async () => lease.assertCurrent(),
  });
  vi.useFakeTimers();
  const { fetch, pending } = fixtureTransport();
  const client = new CognisWebSocketClient();
  const values: unknown[] = [];
  const controller = new SidebarRefreshController(async ({ signal }) => {
    values.push(await api.conversations.sidebar(null, {}, { signal, invalidationOwner: 'refresh' }));
  }, new RefreshCooldown());
  const stop = client.subscribe(event => {
    if (event.type === 'work_invalidated' || event.type === 'scope_invalidated') {
      void controller.request('owner/web');
    }
  });
  try {
    const first = controller.request('owner/web');
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledTimes(1);
    for (let i = 0; i < 100; i++) {
      (client as unknown as { handleMessage(raw: string): void }).handleMessage(
        JSON.stringify({ type: 'work_invalidated', revision: '2' }),
      );
      await vi.advanceTimersByTimeAsync(10);
    }
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(pending[0].signal.aborted).toBe(false);
    pending[0].resolve(response(1));
    await first;
    await vi.advanceTimersByTimeAsync(3_999);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetch).toHaveBeenCalledTimes(2);
    pending[1].resolve(response(2));
    await vi.advanceTimersByTimeAsync(0);
    expect(values).toEqual([{ revision: 1 }, { revision: 2 }]);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetch).toHaveBeenCalledTimes(2);
  } finally {
    stop();
    controller.dispose();
    client.disconnect();
  }
});

it('keeps mutation invalidation and account cancellation effective for refresh-owned reads', async () => {
  const { fetch, pending } = fixtureTransport();
  const result = api.conversations.sidebar(null, {}, { invalidationOwner: 'refresh' });
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  metadataReadFlights.invalidate();
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(pending[0].signal.aborted).toBe(true);
  const rejected = expect(result).rejects.toBeDefined();
  await auth.clear();
  await rejected;
  expect(pending[1].signal.aborted).toBe(true);
  expect(fetch).toHaveBeenCalledTimes(2);
});

it('still invalidates refresh-owned reads for access changes', async () => {
  const { fetch, pending } = fixtureTransport();
  const client = new CognisWebSocketClient();
  try {
    const result = api.conversations.sidebar(null, {}, { invalidationOwner: 'refresh' });
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    (client as unknown as { handleMessage(raw: string): void }).handleMessage(
      JSON.stringify({ type: 'scope_invalidated', reason: 'access_changed' }),
    );
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(pending[0].signal.aborted).toBe(true);
    pending[1].resolve(response(2));
    await expect(result).resolves.toEqual({ revision: 2 });
  } finally {
    client.disconnect();
  }
});
