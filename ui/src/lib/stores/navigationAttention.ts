import { derived, writable } from 'svelte/store';
import { api } from '$lib/api/client';
import { dashboardRealtimeLoads } from '$lib/dashboard/realtime';
import { navigationAttention } from '$lib/navigation-attention';
import { providerNoticeIssues } from '$lib/provider-notices';
import { auth } from '$lib/stores/auth';
import { inbox } from '$lib/stores/inbox';
import { workspaceHealth } from '$lib/system';
import type { NavigationSummary } from '$lib/types/api';
import { wsClient, wsState } from '$lib/ws/client';

export const navigationSummary = writable<NavigationSummary | null>(null);
export const navigationBadges = derived(
  [navigationSummary, inbox, workspaceHealth, auth],
  ([summary, inboxState, health, authState]) => navigationAttention(
    authState.status === 'authenticated' ? summary : null,
    authState.status === 'authenticated' ? inboxState.unreadCount : 0,
    authState.status === 'authenticated' ? providerNoticeIssues(health.health) : [],
  ),
);

/** The authenticated shell owns the lifecycle; each account gets its own request fence. */
export function startNavigationAttention(): () => void {
  let context: { email: string; busy: boolean; dirty: boolean } | null = null;
  let stopped = false;
  let debounce: number | null = null;

  async function refresh(): Promise<void> {
    const current = context;
    if (!current || stopped) return;
    current.dirty = true;
    if (current.busy || document.visibilityState !== 'visible') return;
    current.busy = true;
    try {
      while (current.dirty && context === current && !stopped && document.visibilityState === 'visible') {
        current.dirty = false;
        try {
          const summary = await api.dashboard.navigationSummary();
          if (context === current && !stopped && !current.dirty) navigationSummary.set(summary);
        } catch {
          // Keep the last successful count on transient/offline errors.
        }
      }
    } finally {
      current.busy = false;
    }
  }

  function scheduleRefresh(): void {
    if (context) context.dirty = true;
    if (debounce !== null) return;
    debounce = window.setTimeout(() => {
      debounce = null;
      void refresh();
    }, 200);
  }

  const stopAuth = auth.subscribe((state) => {
    const email = state.status === 'authenticated' ? state.user?.email ?? null : null;
    if (email === (context?.email ?? null)) return;
    context = email ? { email, busy: false, dirty: false } : null;
    navigationSummary.set(null);
    void refresh();
  });
  const stopEvents = wsClient.subscribe((event) => {
    if (
      dashboardRealtimeLoads(event.type, 'reason' in event ? event.reason : undefined).length
      || (event.type === 'scope_invalidated' && event.reason === 'executor_state_changed')
      || event.type === 'work_invalidated'
      || event.type === 'inbox_changed'
    ) scheduleRefresh();
  });
  let previousStatus = '';
  const stopState = wsState.subscribe((state) => {
    if (state.status === 'connected' && previousStatus !== 'connected') scheduleRefresh();
    previousStatus = state.status;
  });
  const onFocus = () => { void refresh(); };
  window.addEventListener('focus', onFocus);
  document.addEventListener('visibilitychange', onFocus);
  const timer = window.setInterval(onFocus, 60_000);
  return () => {
    stopped = true;
    context = null;
    stopAuth();
    stopEvents();
    stopState();
    if (debounce !== null) window.clearTimeout(debounce);
    window.clearInterval(timer);
    window.removeEventListener('focus', onFocus);
    document.removeEventListener('visibilitychange', onFocus);
    navigationSummary.set(null);
  };
}
