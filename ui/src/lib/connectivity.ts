// One connectivity status for the whole app.
//
// Notices follow a precedence: while the connection to Cognis is degraded the
// global ConnectionBanner is the only connectivity notice. Sections hide their
// own load/refresh errors while `$connectivity.degraded`, never show
// connectivity errors themselves (`isConnectivityError`), and reload when the
// connection is restored (`onConnectivityRestored`). Only errors that persist
// with a healthy connection reach section-level UI. Critical failures (event
// store) are never hidden.
//
// Sources: the device network state, the realtime WebSocket (`wsState`), and
// HTTP request outcomes (`$lib/server-reachability`).

import { derived, get, writable, type Readable } from 'svelte/store';
import {
  isConnectivityError,
  onServerRestored,
  probeServerNow,
  reportRequestSuccess,
  serverReachability,
  type ServerReachability,
} from '$lib/server-reachability';
import { wsClient, wsState, type WebSocketState } from '$lib/ws/client';

export { isConnectivityError };

export type ConnectivityLevel =
  | 'ok'
  | 'offline'
  | 'restarting'
  | 'stalled'
  | 'unreachable'
  | 'reconnecting';

export interface ConnectivityState {
  level: ConnectivityLevel;
  /** True while the global banner owns connectivity notices. */
  degraded: boolean;
  /** Last network-level request failure, for the banner's details. */
  lastFailure: string | null;
  /** Realtime reconnect attempts, for the banner's details. */
  attempts: number;
}

// A realtime stall caused by a signed-out session is handled by the login
// flow, not by the connectivity notice.
const AUTH_STALL_REASONS = new Set(['Authentication required', 'Session expired. Please log in again.']);

const deviceOnline = writable(typeof navigator === 'undefined' ? true : navigator.onLine !== false);
if (typeof window !== 'undefined') {
  window.addEventListener('online', () => {
    deviceOnline.set(true);
    if (get(serverReachability).state !== 'ok') reportRequestSuccess();
  });
  window.addEventListener('offline', () => deviceOnline.set(false));
}

/** Highest-precedence connectivity problem, or 'ok'. */
export function combineConnectivity(
  online: boolean,
  ws: Pick<WebSocketState, 'status' | 'attempts' | 'lastError' | 'offline'>,
  server: ServerReachability,
): ConnectivityState {
  let level: ConnectivityLevel = 'ok';
  if (!online || ws.offline === true) level = 'offline';
  else if (server.state === 'restarting') level = 'restarting';
  else if (ws.status === 'stalled' && !AUTH_STALL_REASONS.has(ws.lastError ?? '')) level = 'stalled';
  else if (server.state === 'unreachable') level = 'unreachable';
  else if (ws.status === 'reconnecting') level = 'reconnecting';
  return {
    level,
    degraded: level !== 'ok',
    lastFailure: server.lastFailure,
    attempts: ws.attempts ?? 0,
  };
}

export const connectivity: Readable<ConnectivityState> = derived(
  [deviceOnline, wsState, serverReachability],
  ([$online, $ws, $server]) => combineConnectivity($online, $ws, $server),
);

/** Retry now: reconnect realtime and re-check the server if it was failing. */
export function retryConnectivityNow(): void {
  wsClient.reconnectNow();
  if (get(serverReachability).state !== 'ok') probeServerNow();
}

/** Current status without subscribing. */
export function getConnectivity(): ConnectivityState {
  return get(connectivity);
}

const restoredListeners = new Set<() => void>();
let restoreQueued = false;

function emitRestored(): void {
  // Coalesce: realtime and HTTP often recover in the same moment.
  if (restoreQueued) return;
  restoreQueued = true;
  queueMicrotask(() => {
    restoreQueued = false;
    if (get(connectivity).degraded) return;
    for (const listener of [...restoredListeners]) {
      try {
        listener();
      } catch {
        // One failing listener must not block the others.
      }
    }
  });
}

let previousDegraded = false;
connectivity.subscribe((state) => {
  const recovered = previousDegraded && !state.degraded;
  previousDegraded = state.degraded;
  if (recovered) emitRestored();
});
// A server outage can end while another source keeps the state degraded;
// emitRestored re-checks and only notifies once everything is healthy.
onServerRestored(emitRestored);

/**
 * Run `listener` when the connection to Cognis is restored after an outage
 * (device back online, realtime reconnected, server reachable again).
 * Sections use it to reload data whose load failed meanwhile. Returns an
 * unsubscribe function, usable as an `$effect` / `onDestroy` cleanup.
 */
export function onConnectivityRestored(listener: () => void): () => void {
  restoredListeners.add(listener);
  return () => restoredListeners.delete(listener);
}

// Test hooks -----------------------------------------------------------------

export function __setDeviceOnlineForTests(online: boolean): void {
  deviceOnline.set(online);
}
