import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import 'fake-indexeddb/auto';

vi.mock('$app/environment', () => ({ browser: true }));

import { OFFLINE_SESSION_MAX_AGE_MS, auth, readLastVerifiedUser } from './auth';

const jsonHeaders = { 'Content-Type': 'application/json' };
const user = { email: 'user@example.com', name: 'User', role: 'user' };
const LAST_USER_KEY = 'cognis-auth-last-verified-user';

function meResponse(): Response {
  return new Response(JSON.stringify(user), { status: 200, headers: jsonHeaders });
}

describe('offline auth bootstrap', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    await auth.clear();
    window.localStorage.clear();
  });

  it('remembers the verified user after an online bootstrap', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(meResponse());
    await auth.bootstrap();
    expect(auth.getSnapshot()).toMatchObject({ status: 'authenticated', offline: false });
    expect(readLastVerifiedUser()?.email).toBe('user@example.com');
  });

  it('starts offline with the last verified user when the server is unreachable', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(meResponse());
    await auth.bootstrap();

    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));
    await auth.bootstrap();
    expect(auth.getSnapshot()).toMatchObject({
      status: 'authenticated',
      offline: true,
      user: { email: 'user@example.com' },
    });
  });

  it('treats gateway errors as unreachable, not as logout', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(meResponse());
    await auth.bootstrap();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('bad gateway', { status: 502 }));
    await auth.bootstrap();
    expect(auth.getSnapshot()).toMatchObject({ status: 'authenticated', offline: true });
  });

  it('logs out without a remembered user or after it is too old', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));
    await auth.bootstrap();
    expect(auth.getSnapshot().status).toBe('anonymous');

    window.localStorage.setItem(LAST_USER_KEY, JSON.stringify({
      user,
      verified_at: Date.now() - OFFLINE_SESSION_MAX_AGE_MS - 1,
    }));
    await auth.bootstrap();
    expect(auth.getSnapshot().status).toBe('anonymous');
  });

  it('logs out and notifies listeners when the server later rejects the session', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(meResponse());
    await auth.bootstrap();
    vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await auth.bootstrap();
    expect(auth.getSnapshot().offline).toBe(true);

    const onAnonymous = vi.fn();
    const unsubscribe = auth.onAnonymous(onAnonymous);
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response('{}', { status: 401, headers: jsonHeaders }));
    await auth.revalidate();
    expect(auth.getSnapshot().status).toBe('anonymous');
    expect(onAnonymous).toHaveBeenCalledTimes(1);
    expect(onAnonymous).toHaveBeenCalledWith('expired');
    expect(readLastVerifiedUser()).toBeNull();
    unsubscribe();
  });

  it('returns to a verified online session once the server answers', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(meResponse());
    await auth.bootstrap();
    vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await auth.bootstrap();
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(meResponse());
    await auth.revalidate();
    expect(auth.getSnapshot()).toMatchObject({ status: 'authenticated', offline: false });
  });
});
