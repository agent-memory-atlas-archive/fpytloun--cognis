import { describe, expect, it } from 'vitest';

import { OFFLINE_CACHE_LIMITS, OfflineCache, isOfflineError } from './cache';

// Minimal in-memory IndexedDB covering the operations OfflineCache uses.
type Row = Record<string, unknown> & { key: string };

function asyncRequest<T>(produce: () => T): IDBRequest<T> {
  const request = { result: undefined as T, error: null, onsuccess: null as null | (() => void), onerror: null } as unknown as IDBRequest<T> & { onsuccess: (() => void) | null };
  queueMicrotask(() => {
    (request as { result: T }).result = produce();
    request.onsuccess?.(new Event('success'));
  });
  return request;
}

class FakeTransaction {
  oncomplete: (() => void) | null = null;
  onabort: (() => void) | null = null;
  onerror: (() => void) | null = null;
  error = null;
  private pending = 0;

  constructor(private readonly rows: Map<string, Row>) {
    this.schedule();
  }

  private schedule(): void {
    this.pending += 1;
    setTimeout(() => {
      this.pending -= 1;
      if (this.pending === 0) this.oncomplete?.();
    }, 0);
  }

  objectStore() {
    const rows = this.rows;
    const track = <T>(produce: () => T) => { this.schedule(); return asyncRequest(produce); };
    return {
      get: (key: string) => track(() => rows.get(key)),
      put: (row: Row) => track(() => { rows.set(row.key, structuredClone(row)); return row.key; }),
      delete: (key: string) => track(() => { rows.delete(key); }),
      clear: () => track(() => { rows.clear(); }),
      getAll: () => track(() => [...rows.values()]),
      index: () => ({
        getAll: ([owner, kind]: [string, string]) => track(
          () => [...rows.values()].filter((row) => row.owner === owner && row.kind === kind),
        ),
      }),
    };
  }
}

class FakeDb {
  readonly rows = new Map<string, Row>();
  objectStoreNames = { contains: () => false };
  onversionchange: (() => void) | null = null;
  createObjectStore() {
    return { createIndex: () => undefined };
  }
  deleteObjectStore() {}
  transaction() {
    return new FakeTransaction(this.rows);
  }
  close() {}
}

function fakeFactory(db = new FakeDb()): IDBFactory {
  return {
    open: () => {
      const request = { result: db } as unknown as IDBOpenDBRequest & {
        onupgradeneeded: (() => void) | null;
        onsuccess: (() => void) | null;
      };
      queueMicrotask(() => {
        request.onupgradeneeded?.(new Event('upgradeneeded') as IDBVersionChangeEvent);
        request.onsuccess?.(new Event('success'));
      });
      return request;
    },
  } as unknown as IDBFactory;
}

describe('OfflineCache', () => {
  it('uses the exact opaque encoded scope ID for main/scoped/sidebar persistence', async () => {
    const cache = new OfflineCache(() => fakeFactory());
    const owner = 'offline-cache:account-v2:https%3A%2F%2Fserver.invalid%0Auser%40cognis.test';
    await cache.setOwner(owner);
    expect(cache.currentOwner).toBe(owner);
    expect(await cache.put('conversation-view', 'conversation', { fixture: 1 }, owner)).toBe(true);
    expect(await cache.get('conversation-view', 'conversation', owner)).toEqual({ fixture: 1 });
    expect(await cache.put('scoped-view', 'scope', { fixture: 2 }, owner)).toBe(true);
    expect(await cache.get('scoped-view', 'scope', owner)).toEqual({ fixture: 2 });
    expect(await cache.put('sidebar', 'all', { fixture: 3 }, owner)).toBe(true);
    expect(await cache.get('sidebar', 'all', owner)).toEqual({ fixture: 3 });
    expect(await cache.get('sidebar', 'all', owner.toLowerCase())).toBeNull();
  });
  it('revokes access when the owner changes without deleting retained records', async () => {
    const cache = new OfflineCache(() => fakeFactory());
    expect(await cache.put('sidebar', 'k', { a: 1 })).toBe(false);

    await cache.setOwner('User@Example.com');
    await cache.put('sidebar', 'k', { a: 1 });
    expect(await cache.get('sidebar', 'k')).toEqual({ a: 1 });

    await cache.setOwner('other@example.com');
    expect(await cache.get('sidebar', 'k')).toBeNull();
    await cache.setOwner(null);
    expect(await cache.get('sidebar', 'k')).toBeNull();
  });

  it('does not expose or delete another account data on first bind', async () => {
    const db = new FakeDb();
    const first = new OfflineCache(() => fakeFactory(db));
    await first.setOwner('a@example.com');
    await first.put('meta', 'x', 1);

    const second = new OfflineCache(() => fakeFactory(db));
    await second.setOwner('b@example.com');
    expect(await second.get('meta', 'x')).toBeNull();
    expect(db.rows.size).toBe(1);
  });

  it('evicts the least recently written entries beyond the per-kind limit', async () => {
    const cache = new OfflineCache(() => fakeFactory());
    await cache.setOwner('a@example.com');
    const limit = OFFLINE_CACHE_LIMITS.sidebar;
    for (let index = 0; index <= limit; index += 1) {
      await cache.put('sidebar', `k${index}`, index);
      await new Promise((resolve) => setTimeout(resolve, 2));
    }
    const entries = await cache.list<number>('sidebar');
    expect(entries).toHaveLength(limit);
    expect(entries.map((entry) => entry.id)).not.toContain('k0');
  });

  it('degrades to no cache when IndexedDB is unavailable', async () => {
    const cache = new OfflineCache(() => undefined);
    await cache.setOwner('a@example.com');
    expect(await cache.put('meta', 'x', 1)).toBe(false);
    expect(await cache.get('meta', 'x')).toBeNull();
  });
});

describe('isOfflineError', () => {
  it('recognizes network, timeout, and gateway failures only', () => {
    expect(isOfflineError(new TypeError('Failed to fetch'))).toBe(true);
    expect(isOfflineError({ code: 'request_timeout', status: 0 })).toBe(true);
    expect(isOfflineError({ status: 503 })).toBe(true);
    expect(isOfflineError({ status: 404 })).toBe(false);
    expect(isOfflineError({ status: 401 })).toBe(false);
  });
});
