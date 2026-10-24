import type { DocumentLease } from '$lib/document-coordination';

/** Abort pending transactions on revocation; request success is not commit. */
export function scopedTransaction(
  db: IDBDatabase, store: string, mode: IDBTransactionMode,
  lease?: Pick<DocumentLease, 'owner' | 'signal' | 'assertCurrent'>,
): { store: IDBObjectStore; done: Promise<void>; guard: (action: () => void) => void } {
  lease?.assertCurrent();
  const tx = db.transaction(store, mode);
  const abort = () => { try { tx.abort(); } catch { /* Already settled. */ } };
  lease?.signal.addEventListener('abort', abort, { once: true });
  let failure: unknown;
  let failed = false;
  const done = new Promise<void>((resolve, reject) => {
    const remove = () => lease?.signal.removeEventListener('abort', abort);
    tx.oncomplete = () => {
      remove();
      if (failed) { reject(failure); return; }
      try { lease?.assertCurrent(); resolve(); } catch (error) { reject(error); }
    };
    tx.onabort = tx.onerror = () => {
      remove();
      reject(failed ? failure : tx.error ?? lease?.signal.reason ?? new Error('Storage transaction aborted'));
    };
  });
  // Some callers fail before reaching their await (e.g. DataCloneError).
  void done.catch(() => undefined);
  const guard = (action: () => void) => {
    try { action(); } catch (error) {
      if (!failed) { failed = true; failure = error; }
      abort();
    }
  };
  return { store: tx.objectStore(store), done, guard };
}
