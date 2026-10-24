import { render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Section-level precedence through a real section (InboxList): its load error
// is hidden while the global connection banner applies, and the section
// reloads when the connection is restored.

const mocks = vi.hoisted(() => ({ listeners: new Set<() => void>(), refreshInbox: vi.fn() }));

vi.mock('$lib/connectivity', async () => {
  const { writable } = await import('svelte/store');
  return {
    connectivity: writable({ level: 'ok', degraded: false, lastFailure: null, attempts: 0 }),
    onConnectivityRestored: (listener: () => void) => {
      mocks.listeners.add(listener);
      return () => mocks.listeners.delete(listener);
    },
  };
});

vi.mock('$lib/stores/inbox', async () => {
  const { writable } = await import('svelte/store');
  return {
    inbox: writable({ items: [], unreadCount: 0, unreadOnly: false, loading: false, error: null as string | null }),
    markInboxRead: vi.fn(),
    refreshInbox: mocks.refreshInbox,
    setInboxUnreadOnly: vi.fn(),
  };
});

import InboxList from '$lib/components/InboxList.svelte';
import { connectivity } from '$lib/connectivity';
import { inbox } from '$lib/stores/inbox';

type Writable<T> = { set(value: T): void };
const setConnectivity = (degraded: boolean) => (connectivity as unknown as Writable<object>)
  .set({ level: degraded ? 'reconnecting' : 'ok', degraded, lastFailure: null, attempts: 0 });
const setInboxError = (error: string | null) => (inbox as unknown as Writable<object>)
  .set({ items: [], unreadCount: 0, unreadOnly: false, loading: false, error });

describe('section connectivity precedence', () => {
  beforeEach(() => {
    mocks.listeners.clear();
    mocks.refreshInbox.mockReset();
    setConnectivity(false);
    setInboxError(null);
  });

  it('hides a section error while degraded and reloads it after restoration', async () => {
    let finishRetry: () => void = () => undefined;
    mocks.refreshInbox.mockImplementation(() => new Promise<void>((resolve) => { finishRetry = resolve; }));
    render(InboxList);

    setConnectivity(true);
    setInboxError('Request timed out after 30 seconds.');
    await tick();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByRole('status').textContent).toContain('Loading notifications');

    // Restored: the section retries and keeps the old error hidden meanwhile.
    setConnectivity(false);
    for (const listener of mocks.listeners) listener();
    await tick();
    expect(mocks.refreshInbox).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('alert')).toBeNull();

    // The retry failed for a real reason: now the section shows it.
    setInboxError('Notifications are disabled for this account.');
    finishRetry();
    await new Promise((resolve) => setTimeout(resolve, 0));
    await tick();
    expect(screen.getByRole('alert').textContent).toContain('Notifications are disabled');
  });

  it('does not reload sections without an error', async () => {
    render(InboxList);
    for (const listener of mocks.listeners) listener();
    expect(mocks.refreshInbox).not.toHaveBeenCalled();
  });
});
