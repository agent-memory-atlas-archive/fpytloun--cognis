import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get, writable } from 'svelte/store';
import type { NavigationSummary } from '$lib/types/api';

const mocks = vi.hoisted(() => ({
  load: vi.fn(),
  listener: null as null | ((event: { type: string; reason?: string }) => void),
}));
vi.mock('$lib/api/client', () => ({ api: { dashboard: { navigationSummary: mocks.load } } }));
vi.mock('$lib/stores/auth', () => ({ auth: writable({ status: 'anonymous', user: null as null | { email: string } }) }));
vi.mock('$lib/stores/inbox', () => ({ inbox: writable({ unreadCount: 0 }) }));
vi.mock('$lib/system', () => ({ workspaceHealth: writable({ health: null }) }));
vi.mock('$lib/ws/client', () => ({
  wsClient: { subscribe: (callback: typeof mocks.listener) => { mocks.listener = callback; return () => { mocks.listener = null; }; } },
  wsState: writable({ status: 'idle' }),
}));

import { auth } from '$lib/stores/auth';
import { wsState } from '$lib/ws/client';
import { navigationBadges, navigationSummary, startNavigationAttention } from './navigationAttention';

const data = (tasks = 3): NavigationSummary => ({
  chat_groups: [], dashboard: { total: 0, critical: 0, warning: 0, info: 0, truncated: false },
  tasks, schedules: 1,
});
const flush = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };
const signIn = (email: string | null) => (auth as unknown as ReturnType<typeof writable>).set({
  status: email ? 'authenticated' : 'anonymous', user: email ? { email } : null,
});
let stop: () => void;

beforeEach(() => {
  vi.useFakeTimers();
  signIn(null);
  mocks.load.mockReset().mockResolvedValue(data());
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  stop = startNavigationAttention();
});
afterEach(() => { stop(); vi.restoreAllMocks(); vi.useRealTimers(); });

it('loads from any route and clears on logout', async () => {
  signIn('a@example.com');
  await flush();
  expect(get(navigationBadges)['/tasks'].count).toBe(3);
  signIn(null);
  expect(get(navigationSummary)).toBeNull();
  expect(get(navigationBadges)['/tasks'].count).toBe(0);
});

it('reconciles dashboard counts immediately after executor recovery invalidation', async () => {
  mocks.load.mockResolvedValueOnce({
    ...data(), dashboard: { total: 2, critical: 2, warning: 0, info: 0, truncated: false },
  });
  signIn('a@example.com');
  await flush();
  expect(get(navigationBadges)['/'].count).toBe(2);
  mocks.listener?.({ type: 'scope_invalidated', reason: 'executor_state_changed' });
  await vi.advanceTimersByTimeAsync(200);
  expect(mocks.load).toHaveBeenCalledTimes(2);
  expect(get(navigationBadges)['/'].count).toBe(0);
});

it('fences an old account response and teardown responses', async () => {
  let resolve!: (value: NavigationSummary) => void;
  mocks.load.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  signIn('a@example.com');
  mocks.load.mockResolvedValue(data(9));
  signIn('b@example.com');
  await flush();
  resolve(data(100));
  await flush();
  expect(get(navigationSummary)?.tasks).toBe(9);
  mocks.load.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  window.dispatchEvent(new Event('focus'));
  stop();
  resolve(data(100));
  await flush();
  expect(get(navigationSummary)).toBeNull();
});

it('coalesces event bursts and reconciles an invalidation arriving during a request', async () => {
  signIn('a@example.com');
  await flush();
  let resolve!: (value: NavigationSummary) => void;
  mocks.load.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  for (let index = 0; index < 10; index++) mocks.listener?.({ type: 'conversation_updated' });
  await vi.advanceTimersByTimeAsync(200);
  expect(mocks.load).toHaveBeenCalledTimes(2);
  mocks.listener?.({ type: 'scope_invalidated', reason: 'schedule_action_changed' });
  await vi.advanceTimersByTimeAsync(200);
  expect(mocks.load).toHaveBeenCalledTimes(2);
  mocks.load.mockResolvedValueOnce(data(8));
  resolve(data(4));
  await flush();
  expect(mocks.load).toHaveBeenCalledTimes(3);
  expect(get(navigationSummary)?.tasks).toBe(8);
});

it('refreshes on reconnect and focus, preserves counts on failure, and skips hidden requests', async () => {
  signIn('a@example.com');
  await flush();
  mocks.load.mockRejectedValueOnce(new Error('offline'));
  window.dispatchEvent(new Event('focus'));
  await flush();
  expect(get(navigationSummary)?.tasks).toBe(3);
  (wsState as unknown as ReturnType<typeof writable>).set({ status: 'connected' });
  await vi.advanceTimersByTimeAsync(200);
  expect(mocks.load).toHaveBeenCalledTimes(3);
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
  mocks.listener?.({ type: 'task_paused' });
  await vi.advanceTimersByTimeAsync(200);
  expect(mocks.load).toHaveBeenCalledTimes(3);
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  document.dispatchEvent(new Event('visibilitychange'));
  await flush();
  expect(mocks.load).toHaveBeenCalledTimes(4);
});
