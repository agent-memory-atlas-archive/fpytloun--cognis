import { get } from 'svelte/store';
import { auth } from './stores/auth';
import { documentCoordination } from './document-coordination';
import { isNativeHost, isWorkspaceReplica, nativeVisibility } from './native/host';
import type { RefreshLifecycle, SidebarRefreshController } from './sidebar-refresh';

/** Chat sidebar ownership, independent of focused observation/read receipts. */
export class SidebarRefreshLifecycle {
  constructor(
    private readonly controllers: readonly SidebarRefreshController[],
    private readonly scope: () => string,
  ) {
    for (const controller of controllers) controller.setLifecycle({ scope: null, eligible: false });
  }

  sync(scope = this.scope()): RefreshLifecycle {
    let next: RefreshLifecycle = { scope: null, eligible: false };
    const state = auth.getSnapshot();
    if (state.status === 'authenticated' && state.user && !isWorkspaceReplica()) {
      try {
        const lease = documentCoordination().capture();
        if (lease.owner?.endsWith(`\n${state.user.email.trim().toLowerCase()}`)) {
          next = {
            scope,
            ownerSignal: lease.signal,
            eligible: !state.offline && navigator.onLine && !document.hidden
              && (!isNativeHost() || get(nativeVisibility).visible),
          };
        }
      } catch { /* Unverified/revoked owners cannot schedule reads. */ }
    }
    for (const controller of this.controllers) controller.setLifecycle(next);
    return next;
  }

  start(): () => void {
    const sync = () => { this.sync(); };
    const foreground = () => {
      const state = this.sync();
      if (state.scope && state.eligible) {
        for (const controller of this.controllers) void controller.request(state.scope);
      }
    };
    const stopAuth = auth.subscribe(sync);
    const stopNative = nativeVisibility.subscribe(sync);
    const stopOwner = documentCoordination().onInvalidated(sync);
    window.addEventListener('focus', foreground);
    window.addEventListener('online', foreground);
    window.addEventListener('offline', sync);
    document.addEventListener('visibilitychange', foreground);
    return () => {
      stopAuth(); stopNative(); stopOwner();
      window.removeEventListener('focus', foreground);
      window.removeEventListener('online', foreground);
      window.removeEventListener('offline', sync);
      document.removeEventListener('visibilitychange', foreground);
      for (const controller of this.controllers) controller.dispose();
    };
  }
}
