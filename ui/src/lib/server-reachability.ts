// Reachability of the Cognis server as seen by HTTP requests.
//
// Leaf module (no app imports besides config) so the API clients can report
// into it without an import cycle; `$lib/connectivity` combines it with the
// device and realtime state.
//
// A network-level failure (fetch error, timeout, 502/503/504) is confirmed
// with a cheap readiness probe (`/api/readyz`) before the server counts as
// unreachable or restarting; the probe then repeats with backoff until the
// server answers again.

import { get, writable, type Readable } from 'svelte/store';
import { apiUrl } from '$lib/config';

export type ServerReachabilityState = 'ok' | 'unreachable' | 'restarting';

export interface ServerReachability {
  state: ServerReachabilityState;
  /** Message of the last network-level failure (for diagnostics). */
  lastFailure: string | null;
}

type FailureKind = 'network' | 'timeout' | 'restarting';
type ProbeResult = 'ok' | 'restarting' | 'unreachable';
type ProbeImpl = () => Promise<ProbeResult>;

const PROBE_TIMEOUT_MS = 8_000;
const PROBE_DELAYS_MS = [0, 2_000, 4_000, 8_000, 15_000, 30_000];

function statusOf(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null || !('status' in error)) return undefined;
  const status = (error as { status?: unknown }).status;
  return typeof status === 'number' ? status : undefined;
}

function codeOf(error: unknown): string | undefined {
  if (typeof error !== 'object' || error === null || !('code' in error)) return undefined;
  const code = (error as { code?: unknown }).code;
  return typeof code === 'string' ? code : undefined;
}

function nameOf(error: unknown): string | undefined {
  if (typeof error !== 'object' || error === null) return undefined;
  const name = (error as { name?: unknown }).name;
  return typeof name === 'string' ? name : undefined;
}

/** Network-level failure class of an error, or null for any other error. */
function failureKind(error: unknown): FailureKind | null {
  if (nameOf(error) === 'AbortError') return null; // cancelled by the caller
  if (codeOf(error) === 'request_timeout' || nameOf(error) === 'TimeoutError') return 'timeout';
  if (error instanceof TypeError) return 'network'; // fetch could not reach the server
  if (codeOf(error)?.startsWith('event_store_')) return null; // critical; always shown
  const status = statusOf(error);
  if (status === 503) return 'restarting';
  if (status === 0 || status === 502 || status === 504) return 'network';
  return null;
}

/**
 * True when an error means Cognis could not be reached: a network failure,
 * timeout, gateway error, or a restarting server (503). Such errors belong to
 * the global connectivity notice, not to the section that made the request.
 * Caller-cancelled requests and critical event-store failures are not.
 */
export function isConnectivityError(error: unknown): boolean {
  return failureKind(error) !== null;
}

const store = writable<ServerReachability>({ state: 'ok', lastFailure: null });
export const serverReachability: Readable<ServerReachability> = { subscribe: store.subscribe };

let probeTimer: ReturnType<typeof setTimeout> | null = null;
let probeRunning = false;
let probeAttempt = 0;
/** The current failure episode is a real outage (not just a slow request). */
let outageObserved = false;
const restoredListeners = new Set<() => void>();

async function defaultProbe(): Promise<ProbeResult> {
  // Unit tests never probe the network (they mock fetch); connectivity tests
  // install their own probe.
  if (typeof fetch === 'undefined' || import.meta.env.MODE === 'test') return 'ok';
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    const response = await fetch(apiUrl('/api/readyz'), {
      cache: 'no-store',
      credentials: 'omit',
      signal: controller.signal,
    });
    if (response.ok) return 'ok';
    return response.status === 503 ? 'restarting' : 'unreachable';
  } catch {
    return 'unreachable';
  } finally {
    clearTimeout(timer);
  }
}

let probeImpl: ProbeImpl = defaultProbe;

function scheduleProbe(): void {
  if (probeTimer !== null || probeRunning) return;
  const delay = PROBE_DELAYS_MS[Math.min(probeAttempt, PROBE_DELAYS_MS.length - 1)];
  probeTimer = setTimeout(() => {
    probeTimer = null;
    void runProbe();
  }, delay);
}

async function runProbe(): Promise<void> {
  if (probeRunning) return;
  probeRunning = true;
  probeAttempt += 1;
  let result: ProbeResult;
  try {
    result = await probeImpl();
  } catch {
    result = 'unreachable';
  } finally {
    probeRunning = false;
  }
  if (result === 'ok') {
    const wasOutage = outageObserved;
    probeAttempt = 0;
    outageObserved = false;
    store.set({ state: 'ok', lastFailure: null });
    if (wasOutage) notifyRestored();
    return;
  }
  outageObserved = true;
  store.update((current) => ({ ...current, state: result }));
  scheduleProbe();
}

function notifyRestored(): void {
  for (const listener of [...restoredListeners]) {
    try {
      listener();
    } catch {
      // One failing listener must not block the others.
    }
  }
}

/**
 * Report a failed HTTP request. Returns true when the error is a
 * connectivity error (its notice belongs to the global banner).
 */
export function reportRequestFailure(error: unknown): boolean {
  const kind = failureKind(error);
  if (kind === null) return false;
  const message = error instanceof Error ? error.message : String(error);
  store.update((current) => ({ ...current, lastFailure: message }));
  // Only a failed readiness probe makes this an outage (and a restored event
  // when it ends). A failure the probe contradicts (a slow endpoint, a
  // network blip, one endpoint answering 503) stays that request's own error,
  // so no restore/retry cycle can start from it.
  scheduleProbe();
  return true;
}

/** Report that an HTTP request got an answer (any status) from the server. */
export function reportRequestSuccess(): void {
  if (get(store).state === 'ok' && probeTimer === null) return;
  // A real answer suggests the server is back; confirm right away.
  probeServerNow();
}

/** Check reachability immediately (e.g. the banner's Retry). */
export function probeServerNow(): void {
  if (probeTimer !== null) {
    clearTimeout(probeTimer);
    probeTimer = null;
  }
  probeAttempt = 0;
  void runProbe();
}

/**
 * Called when a server outage (confirmed by the probe, or a network-class
 * failure) ends. Used by `$lib/connectivity` to emit the restored event.
 */
export function onServerRestored(listener: () => void): () => void {
  restoredListeners.add(listener);
  return () => restoredListeners.delete(listener);
}

// Test hooks -----------------------------------------------------------------

export function __setReachabilityProbeForTests(probe: ProbeImpl | null): void {
  probeImpl = probe ?? defaultProbe;
}

export function __resetReachabilityForTests(): void {
  if (probeTimer !== null) clearTimeout(probeTimer);
  probeTimer = null;
  probeRunning = false;
  probeAttempt = 0;
  outageObserved = false;
  store.set({ state: 'ok', lastFailure: null });
}
