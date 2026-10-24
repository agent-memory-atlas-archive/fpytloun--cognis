// Imported only by the temporary workspace acceptance route, never normal routes.
import { browser } from '$app/environment';
import { DocumentCoordination } from '$lib/document-coordination';
import { auth } from '$lib/stores/auth';

if (browser) {
  if (!location.hostname.endsWith('.invalid')) throw new Error('Reserved fixture origin required');
  const target = window as unknown as {
    fixtureAuthTrace?: unknown[];
    fixtureTrace?: (kind: string, value: unknown) => void;
  };
  target.fixtureAuthTrace ??= [];
  target.fixtureTrace = (kind, value) => {
    const entries = target.fixtureAuthTrace!;
    entries.push({ n: entries.length, at: performance.now(), kind, value, stack: new Error(kind).stack });
    if (entries.length > 500) entries.shift();
  };
  const trace = target.fixtureTrace;
  let operation = 0;
  const open = IDBFactory.prototype.open;
  IDBFactory.prototype.open = function (...args) {
    const request = open.apply(this, args);
    if (args[0] === 'cognis-profile-intent-v1') {
      const id = ++operation;
      trace('idb.open.begin', { id });
      for (const event of ['success', 'error', 'blocked', 'upgradeneeded']) {
        request.addEventListener(event, () => trace(`idb.open.${event}`, {
          id, error: request.readyState === 'done' ? request.error?.name : null
        }));
      }
    }
    return request;
  };
  const transaction = IDBDatabase.prototype.transaction;
  IDBDatabase.prototype.transaction = function (...args) {
    const tx = transaction.call(this, typeof args[0] === 'string' ? args[0] : Array.from(args[0]), args[1], args[2]);
    if (this.name === 'cognis-profile-intent-v1') {
      const id = ++operation;
      trace('idb.transaction.begin', { id });
      for (const event of ['complete', 'error', 'abort']) {
        tx.addEventListener(event, (notification) => {
          const request = notification.target as IDBRequest;
          trace(`idb.transaction.${event}`, { id, error: tx.error?.name, message: tx.error?.message,
            requestError: request instanceof IDBRequest ? request.error?.name : null,
            requestMessage: request instanceof IDBRequest ? request.error?.message : null });
        });
      }
    }
    return tx;
  };
  const timeout = window.setTimeout;
  window.setTimeout = ((handler: TimerHandler, delay?: number, ...args: unknown[]) => {
    if (delay === 3000 && typeof handler === 'function') {
      const id = ++operation;
      trace('timeout.arm', { id, delay });
      return timeout(() => { trace('timeout.fire', { id, delay }); handler(...args); }, delay);
    }
    return timeout(handler, delay, ...args);
  }) as typeof window.setTimeout;
  const proto = DocumentCoordination.prototype as unknown as Record<string, (...args: unknown[]) => unknown>;
  const state = (owner: unknown) => {
    const value = owner as { current: { epoch: string; revision: number; blocked: boolean; account: unknown }; verifiedAccount: unknown };
    return { epoch: value.current.epoch, revision: value.current.revision, blocked: value.current.blocked,
      accountPresent: !!value.current.account, verifiedPresent: !!value.verifiedAccount };
  };
  for (const name of ['revoke', 'invalidate', 'beginLogin', 'dispose', 'performTransaction']) {
    const original = proto[name];
    proto[name] = function (...args: unknown[]) {
      if (name !== 'performTransaction') trace(`coordination.${name}`, state(this));
      const before = state(this);
      const result = original.apply(this, args);
      if (result instanceof Promise) return result.then((value) => {
        const after = state(this);
        if (before.epoch !== after.epoch || before.blocked !== after.blocked) {
          trace(`coordination.${name}.changed`, { before, after });
        }
        return value;
      }, (error) => {
        trace(`coordination.${name}.error`, { name: error?.name, message: error?.message,
          stack: error?.stack, state: state(this) });
        throw error;
      });
      return result;
    };
  }
  auth.subscribe((value) => trace('auth.state', {
    status: value.status, userPresent: !!value.user, initialized: value.initialized,
    errorPresent: !!value.error
  }));
  for (const name of ['pageshow', 'pagehide', 'visibilitychange']) {
    window.addEventListener(name, () => trace(`document.${name}`, { visibility: document.visibilityState }));
  }
  window.addEventListener('cognis-workspace', (event) => {
    if ((event as CustomEvent).detail === null) trace('native.workspace-reset', {});
  });
  trace('fixture.module-initialized', {});
}
