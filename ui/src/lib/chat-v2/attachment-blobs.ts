// Durable copies of attachment files that are not uploaded yet.
//
// A message can be sent while its attachments are still uploading (or while
// offline). The file bytes are kept here until the upload succeeds so the
// outbox can finish the upload after a reload or a killed PWA.

import type { DocumentLease } from '$lib/document-coordination';
import { scopedTransaction } from '$lib/offline/scoped-idb';

export interface StoredAttachmentBlob {
  attempted?: boolean;
  local_id: string;
  /** File bytes until the upload succeeds; then dropped in favour of `result`. */
  blob?: Blob | null;
  /** Server reference once uploaded, kept until the message is admitted. */
  result?: import('$lib/types/api').AttachmentRef | null;
  filename: string;
  mime_type: string;
  created_at: number;
}

export const ATTACHMENT_UPLOADS_DB_NAME = 'cognis-chat-v2-uploads';
export const ATTACHMENT_UPLOADS_STORE = 'blobs';
const DB_NAME = ATTACHMENT_UPLOADS_DB_NAME;
const DB_VERSION = 1;
const STORE = 'blobs';
const TIMEOUT_MS = 5_000;
/** Larger files upload only from memory; they cannot survive a reload. */
export const MAX_DURABLE_ATTACHMENT_BYTES = 50 * 1024 * 1024;
/** Orphaned blobs (message deleted, upload long done) are pruned after this. */
const BLOB_MAX_AGE_MS = 14 * 24 * 60 * 60 * 1000;

function withTimeout<T>(promise: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return Promise.race([
    promise,
    new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(new Error('Attachment storage timed out')), TIMEOUT_MS);
    }),
  ]).finally(() => {
    if (timer !== undefined) clearTimeout(timer);
  });
}

function req<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed'));
  });
}

export class AttachmentBlobStore {
  private dbPromise: Promise<IDBDatabase> | null = null;

  constructor(private readonly factory: () => IDBFactory | undefined = () => (
    typeof indexedDB === 'undefined' ? undefined : indexedDB
  ), private readonly name = DB_NAME, private readonly lease?: DocumentLease) {}

  async put(record: StoredAttachmentBlob): Promise<boolean> {
    if (record.blob && record.blob.size > MAX_DURABLE_ATTACHMENT_BYTES) return false;
    try {
      const db = await this.db();
      await this.lease?.validate();
      const { store, done } = scopedTransaction(db, STORE, 'readwrite', this.lease);
      store.put(record);
      await withTimeout(done);
      await this.lease?.validate();
      return true;
    } catch (error) {
      await this.lease?.validate();
      console.warn('Could not persist attachment for offline upload', error);
      return false;
    }
  }

  async get(localId: string): Promise<StoredAttachmentBlob | null> {
    try {
      const db = await this.db();
      await this.lease?.validate();
      const { store, done } = scopedTransaction(db, STORE, 'readonly', this.lease);
      const value = await withTimeout(req(store.get(localId) as IDBRequest<StoredAttachmentBlob | undefined>));
      await done;
      await this.lease?.validate();
      return value ?? null;
    } catch {
      await this.lease?.validate();
      return null;
    }
  }

  async delete(localId: string): Promise<void> {
    try {
      const db = await this.db();
      await this.lease?.validate();
      const { store, done } = scopedTransaction(db, STORE, 'readwrite', this.lease);
      store.delete(localId);
      await withTimeout(done);
      await this.lease?.validate();
    } catch {
      await this.lease?.validate();
      // Best effort; prune() removes leftovers later.
    }
  }

  async prune(keep: Set<string>, now = Date.now()): Promise<void> {
    try {
      const db = await this.db();
      await this.lease?.validate();
      const { store, done } = scopedTransaction(db, STORE, 'readwrite', this.lease);
      const request = store.getAll() as IDBRequest<StoredAttachmentBlob[]>;
      // Delete inside the callback so the transaction stays active.
      request.onsuccess = () => {
        for (const record of request.result) {
          if (!keep.has(record.local_id) && now - record.created_at > BLOB_MAX_AGE_MS) {
            store.delete(record.local_id);
          }
        }
      };
      await withTimeout(done);
      await this.lease?.validate();
    } catch {
      await this.lease?.validate();
      // ignore
    }
  }

  private db(): Promise<IDBDatabase> {
    this.lease?.assertCurrent();
    if (this.dbPromise) return this.dbPromise;
    const factory = this.factory();
    if (!factory) return Promise.reject(new Error('IndexedDB unavailable'));
    this.dbPromise = withTimeout(new Promise<IDBDatabase>((resolve, reject) => {
      const request = factory.open(this.name, DB_VERSION);
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(STORE)) {
          request.result.createObjectStore(STORE, { keyPath: 'local_id' });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error ?? new Error('Opening attachment storage failed'));
    })).catch((error) => {
      this.dbPromise = null;
      throw error;
    });
    return this.dbPromise;
  }
}
