import 'fake-indexeddb/auto';
import { auth } from '$lib/stores/auth';
import type { AuthSessionResponse } from '$lib/types/api';
import { documentCoordination } from '$lib/document-coordination';
import { expect } from 'vitest';

export function authenticatedFixtureResponse(): AuthSessionResponse {
  return {
    status: 'authenticated',
    user: { email: 'user@example.com', name: 'User', role: 'user' },
    expires_at: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

export async function assertFixtureAccount(): Promise<void> {
  expect(auth.getSnapshot().status).toBe('authenticated');
  const lease = documentCoordination().capture();
  expect(lease.owner).toContain('\nuser@example.com');
  await lease.validate();
}

/** A successful fixture server login initializes the real account/lease owner. */
export async function loginFixtureAccount(): Promise<void> {
  const previous = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify(authenticatedFixtureResponse()),
    { status: 200, headers: { 'Content-Type': 'application/json' } });
  try {
    await auth.login('user@example.com', 'fixture-only-password');
    await assertFixtureAccount();
  } finally {
    globalThis.fetch = previous;
  }
}
