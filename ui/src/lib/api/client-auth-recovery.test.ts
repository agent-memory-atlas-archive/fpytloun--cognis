import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import 'fake-indexeddb/auto';

import { api } from '$lib/api/client';
import { auth } from '$lib/stores/auth';

const jsonHeaders = { 'Content-Type': 'application/json' };

function session(): Response {
  return new Response(
    JSON.stringify({
      status: 'authenticated',
      user: { email: 'user@example.com', name: 'User', role: 'user' },
      expires_at: new Date(Date.now() + 3_600_000).toISOString()
    }),
    { status: 200, headers: jsonHeaders }
  );
}

function unauthorized(): Response {
  return new Response(JSON.stringify({ error: { code: 'unauthorized', message: 'expired' } }), {
    status: 401,
    headers: jsonHeaders
  });
}

function me(): Response {
  return new Response(JSON.stringify({ email: 'user@example.com', name: 'User', role: 'user' }), {
    status: 200,
    headers: jsonHeaders
  });
}

function pathOf(input: RequestInfo | URL): string {
  return typeof input === 'string' ? input : input instanceof URL ? input.pathname : input.url;
}

describe('api client 401 recovery', () => {
  const originalFetch = global.fetch;

  beforeEach(async () => {
    await auth.clear();
    global.fetch = vi.fn<typeof fetch>().mockResolvedValueOnce(session());
    await auth.login('user@example.com', 'password123');
    expect(auth.getSnapshot().status).toBe('authenticated');
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it('refreshes once for a burst of 401s and retries each request', async () => {
    let meCalls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const path = pathOf(input);
      if (path.endsWith('/api/auth/refresh')) {
        await new Promise((resolve) => setTimeout(resolve, 5));
        return session();
      }
      meCalls += 1;
      return meCalls <= 3 ? unauthorized() : me();
    });
    global.fetch = fetchMock;

    const results = await Promise.all([api.auth.me(), api.auth.me(), api.auth.me()]);

    expect(results.map((user) => user.email)).toEqual(Array(3).fill('user@example.com'));
    const refreshCalls = fetchMock.mock.calls.filter(([input]) => pathOf(input).endsWith('/api/auth/refresh'));
    expect(refreshCalls).toHaveLength(1);
    expect(auth.getSnapshot().status).toBe('authenticated');
  });

  it('keeps the session when the refresh cannot reach the server', async () => {
    global.fetch = vi.fn<typeof fetch>(async (input) => {
      if (pathOf(input).endsWith('/api/auth/refresh')) throw new TypeError('Failed to fetch');
      return unauthorized();
    });

    await expect(api.auth.me()).rejects.toMatchObject({ status: 401, code: 'unauthorized' });
    expect(auth.getSnapshot().status).toBe('authenticated');
  });

  it('logs out when the refresh rejects the session', async () => {
    global.fetch = vi.fn<typeof fetch>(async () => unauthorized());

    await expect(api.auth.me()).rejects.toMatchObject({ status: 401, code: 'unauthorized' });
    expect(auth.getSnapshot().status).toBe('anonymous');
  });

  it('logs out when the retried request is still unauthorized', async () => {
    global.fetch = vi.fn<typeof fetch>(async (input) => (
      pathOf(input).endsWith('/api/auth/refresh') ? session() : unauthorized()
    ));

    await expect(api.auth.me()).rejects.toMatchObject({ status: 401 });
    expect(auth.getSnapshot().status).toBe('anonymous');
  });
});
