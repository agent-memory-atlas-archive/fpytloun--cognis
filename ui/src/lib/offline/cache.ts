// Persistent per-user offline cache (IndexedDB).
//
// Stores the last-seen conversation views and sidebar projections so the PWA
// can paint instantly on cold start and stay readable without a network.
// The cache is strictly best-effort: every operation has a timeout, failures
// degrade to "no cache", and nothing here is authoritative. Callers always
// reconcile against the server through the normal snapshot/sync paths.
//
// Entries are scoped to the signed-in user (owner). Switching users or
// losing the session wipes the whole database.

import { scopedTransaction } from './scoped-idb';

export type OfflineCacheKind = 'conversation-view' | 'scoped-view' | 'timeline' | 'sidebar' | 'meta';

interface OfflineCacheRecord {
  key: string;
  owner: string;
  kind: OfflineCacheKind;
  id: string;
  value: unknown;
  updated_at: number;
}

export const OFFLINE_DB_NAME = 'cognis-offline';
// Bump when the persisted shapes change incompatibly; old data is dropped.
export const OFFLINE_DB_VERSION = 1;
const STORE = 'entries';
const OPERATION_TIMEOUT_MS = 2_500;
export const OFFLINE_MEDIA_CACHE = 'cognis-media-v1';

/** Max entries kept per kind; least recently written are evicted. */
export const OFFLINE_CACHE_LIMITS: Record<OfflineCacheKind, number> = {
  'conversation-view': 20,
  // Timelines shown in compact chats (dashboard/project modals, task views).
  'scoped-view': 20,
  timeline: 20,
  sidebar: 8,
  meta: 16,
};

function withTimeout<T>(promise: Promise<T>, label: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return Promise.race([
    promise,
    new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(new Error(`${label} timed out`)), OPERATION_TIMEOUT_MS);
    }),
  ]).finally(() => {
    if (timer !== undefined) clearTimeout(timer);
  });
}

function requestToPromise<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed'));
  });
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onabort = () => reject(transaction.error ?? new Error('IndexedDB transaction aborted'));
    transaction.onerror = () => reject(transaction.error ?? new Error('IndexedDB transaction failed'));
  });
}

function recordKey(owner: string, kind: OfflineCacheKind, id: string): string {
  return `${owner}\u0000${kind}\u0000${id}`;
}

export class OfflineCache {
  private dbPromise: Promise<IDBDatabase> | null = null;
  private owner: string | null = null;
  private disabled = false;
  private ownerController = new AbortController();
  private ownerListeners = new Set<() => void>();

  onOwnerChange(listener: () => void): () => void {
    this.ownerListeners.add(listener);
    return () => { this.ownerListeners.delete(listener); };
  }

  constructor(private readonly factory: () => IDBFactory | undefined = () => (
    typeof indexedDB === 'undefined' ? undefined : indexedDB
  )) {}

  /** Bind access to an account; transitions never delete another owner's data. */
  async setOwner(owner: string | null): Promise<void> {
    // Scope IDs contain case-sensitive URL escapes; normalize account inputs
    // before scope construction, never an already encoded namespace.
    const normalized = owner || null;
    if (normalized === this.owner) return;
    this.ownerController.abort();
    this.ownerController = new AbortController();
    this.owner = normalized;
    for (const listener of this.ownerListeners) listener();
  }

  get currentOwner(): string | null {
    return this.owner;
  }

  async get<T>(kind: OfflineCacheKind, id: string, owner = this.owner): Promise<T | null> {
    if (!owner || owner !== this.owner) return null;
    return this.run(async (db) => {
      const { store, done } = this.transaction(db, 'readonly', owner);
      const record = await requestToPromise(
        store.get(recordKey(owner, kind, id)) as IDBRequest<OfflineCacheRecord | undefined>
      );
      await done;
      return record && record.owner === owner ? (record.value as T) : null;
    }, null);
  }

  async put(kind: OfflineCacheKind, id: string, value: unknown, owner = this.owner): Promise<boolean> {
    if (!owner || owner !== this.owner) return false;
    return this.run(async (db) => {
      const { store, done } = this.transaction(db, 'readwrite', owner);
      store.put({
        key: recordKey(owner, kind, id),
        owner,
        kind,
        id,
        value,
        updated_at: Date.now(),
      } satisfies OfflineCacheRecord);
      const request = store.index('owner_kind').getAll([owner, kind]) as IDBRequest<OfflineCacheRecord[]>;
      request.onsuccess = () => {
        const sameKind = request.result;
        const limit = OFFLINE_CACHE_LIMITS[kind];
        if (sameKind.length > limit) {
          sameKind
            .sort((a, b) => a.updated_at - b.updated_at)
            .slice(0, sameKind.length - limit)
            .forEach((record) => store.delete(record.key));
        }
      };
      await done;
      return true;
    }, false);
  }

  async delete(kind: OfflineCacheKind, id: string): Promise<void> {
    const owner = this.owner;
    if (!owner) return;
    await this.run(async (db) => {
      const { store, done } = this.transaction(db, 'readwrite', owner);
      store.delete(recordKey(owner, kind, id));
      await done;
    }, undefined);
  }

  async list<T>(kind: OfflineCacheKind): Promise<Array<{ id: string; value: T; updatedAt: number }>> {
    const owner = this.owner;
    if (!owner) return [];
    return this.run(async (db) => {
      const { store, done } = this.transaction(db, 'readonly', owner);
      const records = await requestToPromise(
        store.index('owner_kind').getAll([owner, kind]) as IDBRequest<OfflineCacheRecord[]>
      );
      await done;
      return records.map((record) => ({ id: record.id, value: record.value as T, updatedAt: record.updated_at }));
    }, []);
  }

  /** Remove cached records belonging to the currently bound owner only. */
  async clear(): Promise<void> {
    const owner = this.owner;
    if (!owner) return;
    await this.run(async (db) => {
      const { store, done } = this.transaction(db, 'readwrite', owner);
      const request = store.openCursor();
      request.onsuccess = () => {
        const cursor = request.result;
        if (!cursor) return;
        if ((cursor.value as OfflineCacheRecord).owner === owner) cursor.delete();
        cursor.continue();
      };
      await done;
    }, undefined);
  }

  private transaction(db: IDBDatabase, mode: IDBTransactionMode, owner: string) {
    const signal = this.ownerController.signal;
    const assertCurrent = () => {
      if (owner !== this.owner || signal.aborted) throw new Error('Offline cache owner changed');
    };
    return scopedTransaction(db, STORE, mode, { owner, signal, assertCurrent });
  }

  private db(): Promise<IDBDatabase> {
    if (this.dbPromise) return this.dbPromise;
    const factory = this.factory();
    if (!factory) return Promise.reject(new Error('IndexedDB unavailable'));
    this.dbPromise = withTimeout(new Promise<IDBDatabase>((resolve, reject) => {
      const request = factory.open(OFFLINE_DB_NAME, OFFLINE_DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (db.objectStoreNames.contains(STORE)) db.deleteObjectStore(STORE);
        const store = db.createObjectStore(STORE, { keyPath: 'key' });
        store.createIndex('owner_kind', ['owner', 'kind'], { unique: false });
      };
      request.onsuccess = () => {
        const db = request.result;
        // Let a newer tab upgrade the schema instead of blocking it.
        db.onversionchange = () => {
          db.close();
          this.dbPromise = null;
        };
        resolve(db);
      };
      request.onerror = () => reject(request.error ?? new Error('Opening offline cache failed'));
      request.onblocked = () => reject(new Error('Offline cache upgrade blocked'));
    }), 'Opening offline cache').catch((error) => {
      this.dbPromise = null;
      throw error;
    });
    return this.dbPromise;
  }

  private async run<T>(operation: (db: IDBDatabase) => Promise<T>, fallback: T): Promise<T> {
    if (this.disabled) return fallback;
    try {
      const db = await this.db();
      return await withTimeout(operation(db), 'Offline cache operation');
    } catch (error) {
      if (error instanceof DOMException && error.name === 'QuotaExceededError') {
        // Out of space: drop the cache rather than failing every write.
        console.warn('Offline cache quota exceeded; clearing cached data', error);
        try {
          const db = await this.db();
          // Never clear unrelated/legacy records on quota failure.
          this.disabled = true;
        } catch {
          this.disabled = true;
        }
      } else {
        console.warn('Offline cache unavailable', error);
      }
      return fallback;
    }
  }
}

export const offlineCache = new OfflineCache();

/**
 * Ask the browser to keep this origin's storage. Without it, iOS can evict
 * IndexedDB/CacheStorage after about a week of not opening the app.
 */
export async function requestPersistentStorage(): Promise<boolean> {
  try {
    if (typeof navigator === 'undefined' || !navigator.storage?.persist) return false;
    if (await navigator.storage.persisted?.()) return true;
    return await navigator.storage.persist();
  } catch {
    return false;
  }
}

/**
 * Ask the service worker (which owns media writes) to invalidate in-flight
 * writes and drop the media cache; resolves on its acknowledgement.
 */
async function clearServiceWorkerMediaCache(timeoutMs = 2_000): Promise<void> {
  const controller = typeof navigator !== 'undefined' ? navigator.serviceWorker?.controller : null;
  if (!controller || typeof MessageChannel === 'undefined') return;
  await new Promise<void>((resolve) => {
    const channel = new MessageChannel();
    const timer = setTimeout(resolve, timeoutMs);
    channel.port1.onmessage = () => {
      clearTimeout(timer);
      resolve();
    };
    try {
      controller.postMessage({ type: 'CLEAR_MEDIA_CACHE' }, [channel.port2]);
    } catch {
      clearTimeout(timer);
      resolve();
    }
  });
}

/**
 * Clear every record in one object store without deleting the database
 * (other code in this page may hold an open connection to it).
 */
export async function clearIndexedDbStore(dbName: string, storeName: string): Promise<void> {
  if (typeof indexedDB === 'undefined') return;
  await withTimeout(new Promise<void>((resolve, reject) => {
    const request = indexedDB.open(dbName);
    request.onupgradeneeded = () => {
      // The database did not exist; nothing to clear. Abort the creation.
      request.transaction?.abort();
    };
    request.onerror = () => resolve();
    request.onsuccess = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(storeName)) {
        db.close();
        resolve();
        return;
      }
      const transaction = db.transaction(storeName, 'readwrite');
      transaction.objectStore(storeName).clear();
      transaction.oncomplete = () => {
        db.close();
        resolve();
      };
      transaction.onerror = () => {
        db.close();
        reject(transaction.error ?? new Error(`Clearing ${dbName} failed`));
      };
    };
  }), `Clearing ${dbName}`).catch((error) => console.warn('Offline data clear failed', error));
}

/** Wipe cached conversation data and viewed media (keeps unsent messages). */
export async function clearOfflineData(): Promise<void> {
  await offlineCache.clear();
  await clearServiceWorkerMediaCache();
  try {
    if (typeof caches !== 'undefined') {
      const names = await caches.keys();
      await Promise.all(names.filter((name) => name.startsWith('cognis-media-')).map((name) => caches.delete(name)));
    }
  } catch {
    // CacheStorage can be unavailable (private mode); nothing to clear.
  }
}

/** True when an error means the network/server could not be reached. */
export function isOfflineError(error: unknown): boolean {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return true;
  if (error instanceof TypeError) return true;
  if (error instanceof DOMException && (error.name === 'AbortError' || error.name === 'TimeoutError')) return true;
  const code = typeof error === 'object' && error !== null && 'code' in error ? (error as { code?: unknown }).code : undefined;
  if (code === 'request_timeout') return true;
  const status = typeof error === 'object' && error !== null && 'status' in error ? (error as { status?: unknown }).status : undefined;
  return status === 0 || status === 502 || status === 503 || status === 504;
}
