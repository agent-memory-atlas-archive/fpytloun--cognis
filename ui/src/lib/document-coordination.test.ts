import { describe, expect, it, vi } from 'vitest';
import { IDBDatabase, IDBFactory, IDBObjectStore } from 'fake-indexeddb';
import { DocumentCoordination, StaleDocumentError, CoordinationUnavailableError } from './document-coordination';
import { TestWebLocks } from '../test/web-locks';

function fixture() {
  const indexedDB = new IDBFactory();
  const locks = new TestWebLocks() as unknown as LockManager;
  // No event delivery and permanently stale localStorage, even inside Web Locks.
  const storage = { getItem: () => null, setItem: vi.fn(() => { throw new Error('quota'); }) } as unknown as Storage;
  const create = () => new DocumentCoordination({
    indexedDB, storage, locks, profile: () => 'https://transaction.coordination.invalid',
    generation: () => 'one', uuid: () => crypto.randomUUID(),
    subscribe: () => () => {}, publish: () => {},
  });
  const raw = async (value?: unknown) => {
    const db = await new Promise<IDBDatabase>((resolve) => {
      const request = indexedDB.open('cognis-profile-intent-v1', 1);
      request.onsuccess = () => resolve(request.result);
    });
    await new Promise<void>((resolve) => {
      const tx = db.transaction('profiles', 'readwrite');
      const store = tx.objectStore('profiles');
      if (value === undefined) store.delete('https://transaction.coordination.invalid');
      else store.put(value, 'https://transaction.coordination.invalid');
      tx.oncomplete = () => resolve();
    });
    db.close();
  };
  return { create, indexedDB, storage, raw };
}

describe('transactional profile authority', () => {
  it('concurrent cold processes converge without localStorage visibility or notification delivery', async () => {
    const f = fixture(), a = f.create(), b = f.create();
    await Promise.all([a.initialize(), b.initialize()]);
    expect(a.capture(false).epoch).toBe(b.capture(false).epoch);
    await Promise.all([a.verified('one@coordination.invalid'), b.verified('one@coordination.invalid')]);
    await a.capture().validate();
    expect(a.owner).toBe(b.owner);
    expect(f.storage.setItem).not.toHaveBeenCalled();
    a.dispose(); b.dispose();
  });

  it('unverified documents cannot revoke a verified identity or replace it', async () => {
    const f = fixture(), a = f.create(), b = f.create();
    await a.initialize(); await a.verified('one@coordination.invalid');
    await b.initialize();
    expect(b.capture(false).owner).toBeNull();
    await expect(b.invalidate()).rejects.toThrow(StaleDocumentError);
    await expect(b.verified('two@coordination.invalid')).rejects.toThrow(StaleDocumentError);
    await a.capture().validate();
    a.dispose(); b.dispose();
  });

  it('late logout, verification and refresh callbacks cannot revoke or resurrect newer login', async () => {
    const f = fixture(), a = f.create(), b = f.create();
    await a.initialize(); await a.verified('one@coordination.invalid');
    const old = a.capture();
    await b.beginLogin(); await b.verified('two@coordination.invalid');
    const newer = b.capture();
    await expect(a.refreshed(old)).rejects.toThrow(StaleDocumentError);
    await expect(a.invalidate(true, old)).rejects.toThrow(StaleDocumentError);
    await expect(a.verified('one@coordination.invalid', old)).rejects.toThrow(StaleDocumentError);
    await newer.validate();
    await expect(old.validate()).rejects.toThrow(StaleDocumentError);
    expect(b.owner).toContain('two@coordination.invalid');
    a.dispose(); b.dispose();
  });

  for (const corrupt of [false, true]) {
    it(`revokes missing/corrupt authority without reconstructing cached identity: corrupt=${corrupt}`, async () => {
      const f = fixture(), a = f.create();
      await a.initialize(); await a.verified('one@coordination.invalid');
      const lease = a.capture();
      await f.raw(corrupt ? { epoch: 'broken' } : undefined);
      await expect(lease.validate()).rejects.toThrow(StaleDocumentError);
      expect(lease.signal.aborted).toBe(true);
      expect(a.owner).toBeNull();
      await expect(a.initialize()).rejects.toThrow(StaleDocumentError);
      await expect(a.resumeCachedAccount('one@coordination.invalid')).rejects.toThrow(StaleDocumentError);
      a.dispose();
    });
  }

  it('offline resume needs matching transactional identity, never cached user alone', async () => {
    const f = fixture(), a = f.create(), b = f.create();
    await a.initialize();
    expect(await a.resumeCachedAccount('one@coordination.invalid')).toBe(false);
    await a.verified('one@coordination.invalid');
    await b.initialize();
    expect(await b.resumeCachedAccount('one@coordination.invalid')).toBe(true);
    await a.invalidate();
    expect(await b.resumeCachedAccount('one@coordination.invalid')).toBe(false);
    a.dispose(); b.dispose();
  });

  it('fails explicitly on unavailable IDB and quota without storage fallback', async () => {
    const f = fixture();
    const open = vi.spyOn(f.indexedDB, 'open').mockImplementation(() => { throw new Error('unavailable'); });
    const a = f.create();
    await expect(a.initialize()).rejects.toThrow(CoordinationUnavailableError);
    open.mockRestore();
    const put = vi.spyOn(IDBObjectStore.prototype, 'put').mockImplementation(() => {
      throw new DOMException('Quota', 'QuotaExceededError');
    });
    try {
      await expect(a.initialize()).rejects.toThrow();
      expect(a.owner).toBeNull();
      expect(f.storage.setItem).not.toHaveBeenCalled();
    } finally { put.mockRestore(); a.dispose(); }
  });

  it('fails a blocked IDB open without waiting for a Web Lock or publishing intent', async () => {
    const f = fixture();
    const request = {} as IDBOpenDBRequest;
    vi.spyOn(f.indexedDB, 'open').mockImplementation(() => {
      queueMicrotask(() => request.onblocked?.call(request, new Event('blocked') as IDBVersionChangeEvent));
      return request;
    });
    const a = f.create();
    await expect(a.initialize()).rejects.toThrow(CoordinationUnavailableError);
    expect(f.storage.setItem).not.toHaveBeenCalled();
    a.dispose();
  });

  for (const abortThrows of [false, true]) {
    it(`settles a suspended transaction without abort events and permits recovery: abortThrows=${abortThrows}`, async () => {
      const f = fixture(), a = f.create();
      await a.initialize();
      await a.verified('one@coordination.invalid');
      const lease = a.capture();
      const abort = vi.fn(() => {
        if (abortThrows) throw new DOMException('Transaction is already inactive', 'InvalidStateError');
      });
      const request = {} as IDBRequest;
      const tx = {
        objectStore: () => ({ get: () => request }),
        abort,
      } as unknown as IDBTransaction;
      const transaction = vi.spyOn(IDBDatabase.prototype, 'transaction').mockReturnValueOnce(tx);
      let outcome = 'pending';
      const pending = lease.validate().then(
        () => { outcome = 'fulfilled'; },
        error => {
          expect(error).toBeInstanceOf(CoordinationUnavailableError);
          outcome = 'rejected';
        },
      );
      try {
        await vi.waitFor(() => expect(abort).toHaveBeenCalled(), { timeout: 4_000 });
        expect(outcome).toBe('rejected');
        await pending;
        expect(lease.signal.aborted).toBe(true);
        expect(a.owner).toBeNull();
        // Late storage callbacks cannot revive timed-out authority or invoke the
        // stale transition (which would attempt to abort again on missing data).
        request.onsuccess?.call(request, new Event('success'));
        tx.oncomplete?.call(tx, new Event('complete'));
        expect(abort).toHaveBeenCalledOnce();
        expect(a.owner).toBeNull();
        await a.initialize();
        await a.verified('one@coordination.invalid');
        await a.capture().validate();
      } finally {
        transaction.mockRestore();
        a.dispose();
      }
    }, 6_000);
  }

  it('validates authority after acquiring a lock, with no nested metadata lock', async () => {
    const f = fixture(), a = f.create(), b = f.create();
    await a.initialize(); await a.verified('one@coordination.invalid');
    await b.initialize(); await b.verified('one@coordination.invalid');
    const old = a.capture();
    await b.invalidate();
    const action = vi.fn(async () => {});
    await expect(a.run('send', old, action)).rejects.toThrow(StaleDocumentError);
    expect(action).not.toHaveBeenCalled();
    a.dispose(); b.dispose();
  });
});
