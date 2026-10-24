/** The only durable owner of coordination metadata. No credentials or user data. */
export interface ProfileIntent {
  epoch: string;
  account: string | null;
  blocked: boolean;
  refresh: string;
  revision: number;
}

export class CoordinationUnavailableError extends Error {
  constructor() {
    super('Safe window coordination requires available IndexedDB and Web Locks. Reconnect or retry; retained data has not been removed.');
    this.name = 'CoordinationUnavailableError';
  }
}

export function validIntent(value: unknown): value is ProfileIntent {
  if (!value || typeof value !== 'object') return false;
  const v = value as ProfileIntent;
  return typeof v.epoch === 'string' && v.epoch.length > 0
    && (v.account === null || (typeof v.account === 'string' && v.account.length > 0))
    && typeof v.blocked === 'boolean' && typeof v.refresh === 'string'
    && Number.isSafeInteger(v.revision) && v.revision > 0;
}

/** Callbacks are synchronous: no network/locks/await inside an IDB transaction.
 * Completion, not request success, is the linearization acknowledgement.
 */
export class ProfileIntentStore {
  constructor(private readonly factory: IDBFactory | undefined) {}

  private open(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
      if (!this.factory) { reject(new CoordinationUnavailableError()); return; }
      let settled = false;
      const fail = () => {
        settled = true;
        clearTimeout(timer);
        reject(new CoordinationUnavailableError());
      };
      const timer = setTimeout(fail, 3_000);
      try {
        const request = this.factory.open('cognis-profile-intent-v1', 1);
        request.onblocked = request.onerror = fail;
        request.onupgradeneeded = () => {
          if (settled) { request.transaction?.abort(); return; }
          request.result.createObjectStore('profiles');
        };
        request.onsuccess = () => {
          clearTimeout(timer);
          if (settled) { request.result.close(); return; }
          settled = true;
          resolve(request.result);
        };
      } catch { fail(); }
    });
  }

  async transact(profile: string, change: (raw: unknown) => ProfileIntent): Promise<ProfileIntent> {
    const db = await this.open();
    try {
      return await new Promise<ProfileIntent>((resolve, reject) => {
        const tx = db.transaction('profiles', 'readwrite');
        const store = tx.objectStore('profiles');
        let result: ProfileIntent;
        let failure: unknown;
        let settled = false;
        const fail = () => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          reject(failure ?? new CoordinationUnavailableError());
        };
        const timer = setTimeout(() => {
          failure = new CoordinationUnavailableError();
          // A suspended IDB backend may never deliver the abort event. Settle
          // locally so this transaction cannot wedge the document's queue.
          fail();
          try { tx.abort(); } catch { /* Already completed. */ }
        }, 3_000);
        tx.oncomplete = () => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          resolve(result);
        };
        tx.onabort = tx.onerror = fail;
        const request = store.get(profile);
        request.onsuccess = () => {
          if (settled) return;
          try {
            result = change(request.result);
            if (result !== request.result) store.put(result, profile);
          } catch (error) {
            failure = error;
            tx.abort();
          }
        };
      });
    } finally { db.close(); }
  }
}
