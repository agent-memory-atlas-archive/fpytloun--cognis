import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get, writable } from 'svelte/store';

const mocks = vi.hoisted(() => ({ list: vi.fn(), read: vi.fn(), toast: vi.fn(), listener: null as null | ((event: { type: string }) => void) }));
vi.mock('$lib/api/client', () => ({ api: { inbox: { list: mocks.list, markRead: mocks.read } } }));
vi.mock('$lib/stores/toasts', () => ({ addToast: mocks.toast }));
vi.mock('$lib/stores/auth', () => ({ auth: writable({ status: 'anonymous', user: null as null | { email: string } }) }));
vi.mock('$lib/ws/client', () => ({
  wsClient: { subscribe: (callback: typeof mocks.listener) => { mocks.listener = callback; return () => { mocks.listener = null; }; } },
  wsState: writable({ status: 'idle' }),
}));
import { auth } from '$lib/stores/auth';
import { inbox, markInboxRead, refreshInbox, setInboxUnreadOnly, startInbox } from './inbox';

const item = { notification_id: 'inbox-a', kind: 'sharing.agent.shared', title: 'Agent shared', body: 'Shared agent', href: '/agents/a', created_at: '2026-01-01T00:00:00Z', read_at: null };
const page = { items: [item], unread_count: 1, next_cursor: null };
const flush = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };
let stop: () => void;
function signIn(email: string): void {
  (auth as unknown as ReturnType<typeof writable>).set({ status: 'authenticated', user: { email } });
}
beforeEach(() => {
  mocks.list.mockReset().mockResolvedValue(page);
  mocks.read.mockReset().mockResolvedValue({ ok: true });
  mocks.toast.mockReset();
  stop = startInbox();
});
afterEach(() => { stop(); vi.restoreAllMocks(); });

describe('notification inbox', () => {
  it('acknowledges a multi-page snapshot in bounded batches', async () => {
    signIn('a@example.com');
    await flush();
    const ids = Array.from({ length: 120 }, (_, index) => `inbox-${index}`);
    await markInboxRead(ids);
    expect(mocks.read.mock.calls.map(([batch]) => batch.length)).toEqual([100, 20]);
    expect(mocks.read).toHaveBeenNthCalledWith(2, ids.slice(100));
  });
  it('loads unread state without toasting existing history and clears it on account change', async () => {
    signIn('a@example.com');
    await flush();
    expect(get(inbox).unreadCount).toBe(1);
    expect(mocks.toast).not.toHaveBeenCalled();
    mocks.list.mockResolvedValue({ items: [], unread_count: 0, next_cursor: null });
    signIn('b@example.com');
    expect(get(inbox).items).toEqual([]);
    await flush();
    expect(get(inbox).unreadCount).toBe(0);
  });
  it('discards an old account response after a switch', async () => {
    let resolve!: (value: typeof page) => void;
    mocks.list.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    signIn('a@example.com');
    mocks.list.mockResolvedValue({ items: [], unread_count: 0, next_cursor: null });
    signIn('b@example.com');
    await flush();
    resolve(page);
    await flush();
    expect(get(inbox).items).toEqual([]);
  });
  it('uses server-side unread filtering and recipient-scoped acknowledgement', async () => {
    signIn('a@example.com');
    await flush();
    setInboxUnreadOnly(true);
    await flush();
    expect(mocks.list).toHaveBeenLastCalledWith({ cursor: null, unread: true });
    await markInboxRead([item.notification_id]);
    expect(mocks.read).toHaveBeenCalledWith([item.notification_id]);
  });
  it('deduplicates toasts for repeated realtime hints', async () => {
    vi.spyOn(document, 'hasFocus').mockReturnValue(true);
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    mocks.list.mockResolvedValueOnce({ items: [], unread_count: 0, next_cursor: null });
    signIn('a@example.com');
    await flush();
    mocks.listener?.({ type: 'inbox_changed' });
    await flush();
    mocks.listener?.({ type: 'inbox_changed' });
    await flush();
    expect(mocks.toast).toHaveBeenCalledTimes(1);
  });
  it('does not strand loading state when append is requested during refresh', async () => {
    let resolve!: (value: typeof page) => void;
    mocks.list.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    signIn('a@example.com');
    await refreshInbox(true);
    resolve(page);
    await flush();
    expect(get(inbox).loading).toBe(false);
  });
});
