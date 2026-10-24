/// <reference types="@sveltejs/kit" />
/// <reference lib="webworker" />

// Cognis PWA service worker.
//
// Strategy (deliberately conservative):
//   - Precache the static app shell (SvelteKit build artifacts + prerendered
//     HTML + static files). These are user-agnostic and hash-busted per deploy.
//   - Runtime-cache static-looking assets (images/fonts) only. User-specific
//     API payloads are NEVER cached to avoid cross-user data leaks on shared
//     devices after logout/login.
//   - API requests pass through to the network. If the network fails, return
//     a structured JSON offline error (503), NEVER the HTML shell (which
//     would break JSON-consuming code paths).
//   - WebSocket upgrades and /api/* POST/PUT/PATCH/DELETE requests pass
//     through unchanged.
//   - Navigation requests fall back to the precached app shell so the SPA
//     still boots offline.
//
// Update UX:
//   - New SW versions activate themselves and notify clients. The page is the
//     single reload owner so activation cannot race a service-worker-driven
//     navigation against a page-side reload.
//   - `clients.claim()` is called on activate so the newly-activated SW takes
//     control of already-open tabs immediately.
//   - When this is an update over a previous Cognis app-shell cache, controlled
//     windows are notified so they cross to the new JS runtime.

import { build, files, prerendered, version } from '$service-worker';
import { PushObservationRegistry } from '$lib/push-observation';
import { MediaScopes } from '$lib/offline/media-scope';
const mediaScopes = new MediaScopes();

const sw = self as unknown as ServiceWorkerGlobalScope;

const PRECACHE = `cognis-precache-${version}`;
const RUNTIME = `cognis-runtime-${version}`;
const COGNIS_CACHE_PREFIX = 'cognis-';
const CACHE_OPERATION_TIMEOUT_MS = 3_000;
const NAVIGATION_FETCH_TIMEOUT_MS = 8_000;
const PUSH_OBSERVATION_DB = 'cognis-push-observations';
const PUSH_OBSERVATION_STORE = 'observations';
const PUSH_OBSERVATION_TTL_MS = 24 * 60 * 60 * 1000;

// Install-time precache is limited to what an offline boot needs: code
// (JS/CSS), prerendered HTML, the manifest, and app icons. Images, fonts,
// splash screens, docs, fixtures, and lazily loaded workers are cached on
// first use instead, so an install or update does not pull tens of MB over a
// cellular link.
const PRECACHE_BUILD_ASSET = /\.(?:js|css)$/i;
const PRECACHE_STATIC_FILES = new Set([
  '/manifest.webmanifest',
  '/favicon.ico',
  '/favicon.svg',
  '/brand/cognis-mark.svg',
  '/brand/cognis-mark-color.svg',
  '/pwa/badge-96.png',
  '/pwa/icon.svg',
  '/pwa/icon-192.png',
  '/pwa/icon-512.png',
  '/pwa/icon-maskable-512.png',
  '/pwa/apple-touch-icon.png'
]);

const PRECACHE_URLS = [
  ...build.filter((f) => PRECACHE_BUILD_ASSET.test(f)),
  ...files.filter((f) => PRECACHE_STATIC_FILES.has(f)),
  ...prerendered
];
const PRECACHE_URL_SET = new Set(PRECACHE_URLS);
const IMMUTABLE_PREFIX = '/_app/immutable/';

/**
 * Fill the new precache, reusing content-hashed immutable files from the
 * previous version's caches. Only files that changed in this deploy are
 * downloaded, which keeps updates small on slow connections.
 */
async function populatePrecache(cache: Cache): Promise<void> {
  const previousCaches: Cache[] = [];
  for (const name of await caches.keys()) {
    if (!name.startsWith(COGNIS_CACHE_PREFIX) || name === PRECACHE) continue;
    try {
      previousCaches.push(await openCacheWithTimeout(name));
    } catch {
      // A broken old cache only costs a re-download.
    }
  }
  const missing: string[] = [];
  for (const url of PRECACHE_URLS) {
    // Already fetched by an earlier, interrupted install of this version.
    try {
      if ((await matchCacheWithTimeout(cache, url))?.ok) continue;
    } catch {
      // Treat as missing.
    }
    let reused = false;
    if (url.startsWith(IMMUTABLE_PREFIX)) {
      for (const previous of previousCaches) {
        try {
          const response = await matchCacheWithTimeout(previous, url);
          if (response?.ok) {
            await cache.put(url, response);
            reused = true;
            break;
          }
        } catch {
          // Fall through to a network fetch.
        }
      }
    }
    if (!reused) missing.push(url);
  }
  await downloadIntoCache(cache, missing);
}

const PRECACHE_FETCH_CONCURRENCY = 4;
const PRECACHE_FETCH_ATTEMPTS = 3;

/**
 * Download files one by one (a few in parallel) with retries, keeping every
 * file that arrives. `cache.addAll` is all-or-nothing: on a weak mobile link
 * one failed file discarded the whole update and the next attempt started
 * from zero, so the phone kept running an old build. If anything is still
 * missing the install fails, and the next attempt resumes from what is
 * already stored in this version's cache.
 */
async function downloadIntoCache(cache: Cache, urls: string[]): Promise<void> {
  const queue = [...urls];
  const failed: string[] = [];
  const worker = async () => {
    for (let url = queue.shift(); url !== undefined; url = queue.shift()) {
      let stored = false;
      for (let attempt = 0; attempt < PRECACHE_FETCH_ATTEMPTS && !stored; attempt += 1) {
        try {
          const response = await fetch(url, { cache: 'no-cache', credentials: 'same-origin' });
          if (response.ok) {
            await cache.put(url, response);
            stored = true;
          }
        } catch {
          // Retry after a short backoff.
        }
        if (!stored) await new Promise((resolve) => setTimeout(resolve, 500 * 2 ** attempt));
      }
      if (!stored) failed.push(url);
    }
  };
  await Promise.all(Array.from({ length: PRECACHE_FETCH_CONCURRENCY }, worker));
  if (failed.length > 0) {
    throw new Error(`Precache incomplete: ${failed.length} of ${urls.length} files failed`);
  }
}

sw.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(PRECACHE);
      await populatePrecache(cache);
      await sw.skipWaiting();
    })()
  );
});

sw.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      const staleCognisCaches = names
        .filter((n) => (
          n.startsWith(COGNIS_CACHE_PREFIX)
          && n !== PRECACHE
          && n !== RUNTIME
           // Preserve legacy/account media across updates and logout.
          && !n.startsWith('cognis-media-')
        ));
      const isUpdate = staleCognisCaches.length > 0;

      await sw.clients.claim();

      if (isUpdate) {
        await reloadControlledWindowClients();
      }

      await Promise.all(staleCognisCaches.map((n) => caches.delete(n)));
    })()
  );
});

async function reloadControlledWindowClients(): Promise<void> {
  const clients = await sw.clients.matchAll({ type: 'window', includeUncontrolled: true });
  await Promise.all(
    clients.map(async (client) => {
      const windowClient = client as WindowClient;
      try {
        const url = new URL(windowClient.url);
        if (url.origin !== sw.location.origin) return;
        windowClient.postMessage({ type: 'COGNIS_SW_UPDATED', version });
      } catch {
        // The client may close during activation. Other clients should still
        // update, and a future navigation will use this SW.
      }
    })
  );
}

type WebPushPayload = {
  title?: string;
  body?: string;
  url?: string;
  tag?: string;
  kind?: string;
  conversation_id?: string;
  occurred_at?: string;
  icon?: unknown;
  notification_id?: string;
  actions?: Array<{ action: string; title: string }>;
};

type ActiveConversationMessage = {
  type?: string;
  conversation_id?: string | null;
  active?: boolean;
  observed_at?: string;
};

type ServiceWorkerControlMessage = ActiveConversationMessage & {
  type?: 'GET_VERSION' | 'SKIP_WAITING' | 'ACTIVE_CONVERSATION' | 'CONVERSATION_OBSERVED' | 'CLEAR_MEDIA_CACHE' | 'BIND_MEDIA_SCOPE' | 'REVOKE_MEDIA_SCOPE';
  owner?: string;
  epoch?: string;
};

const activeConversationByClient = new Map<string, string>();
const pushObservations = new PushObservationRegistry();
let pushObservationDbPromise: Promise<IDBDatabase> | null = null;

type StoredPushObservation = {
  key: string;
  client_id: string;
  conversation_id: string;
  observed_at: string;
  expires_at: number;
};

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function transactionComplete(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onabort = () => reject(transaction.error ?? new Error('IndexedDB transaction aborted'));
    transaction.onerror = () => reject(transaction.error ?? new Error('IndexedDB transaction failed'));
  });
}

function pushObservationDb(): Promise<IDBDatabase> {
  if (pushObservationDbPromise) return pushObservationDbPromise;
  pushObservationDbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(PUSH_OBSERVATION_DB, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(PUSH_OBSERVATION_STORE)) {
        request.result.createObjectStore(PUSH_OBSERVATION_STORE, { keyPath: 'key' });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => {
      pushObservationDbPromise = null;
      reject(request.error);
    };
  });
  return pushObservationDbPromise;
}

async function persistPushObservation(
  clientId: string,
  conversationId: unknown,
  observedAt: unknown,
): Promise<void> {
  const normalizedConversationId = typeof conversationId === 'string' ? conversationId.trim() : '';
  if (!normalizedConversationId || typeof observedAt !== 'string' || !Number.isFinite(Date.parse(observedAt))) return;
  const db = await pushObservationDb();
  const transaction = db.transaction(PUSH_OBSERVATION_STORE, 'readwrite');
  const completion = transactionComplete(transaction);
  transaction.objectStore(PUSH_OBSERVATION_STORE).put({
    key: `${clientId}:${normalizedConversationId}`,
    client_id: clientId,
    conversation_id: normalizedConversationId,
    observed_at: observedAt,
    expires_at: Date.now() + PUSH_OBSERVATION_TTL_MS,
  } satisfies StoredPushObservation);
  await completion;
}

async function restorePushObservations(clientIds: string[]): Promise<void> {
  const db = await pushObservationDb();
  const transaction = db.transaction(PUSH_OBSERVATION_STORE, 'readonly');
  const stored = await requestResult(
    transaction.objectStore(PUSH_OBSERVATION_STORE).getAll() as IDBRequest<StoredPushObservation[]>,
  );
  const retainedClientIds = new Set(clientIds);
  const now = Date.now();
  const expiredKeys: string[] = [];
  for (const observation of stored) {
    if (observation.expires_at <= now || !retainedClientIds.has(observation.client_id)) {
      expiredKeys.push(observation.key);
      continue;
    }
    pushObservations.record(
      observation.client_id,
      observation.conversation_id,
      observation.observed_at,
    );
  }
  if (expiredKeys.length === 0) return;
  const cleanup = db.transaction(PUSH_OBSERVATION_STORE, 'readwrite');
  const completion = transactionComplete(cleanup);
  const store = cleanup.objectStore(PUSH_OBSERVATION_STORE);
  for (const key of expiredKeys) store.delete(key);
  await completion;
}

sw.addEventListener('message', (event) => {
  const data = event.data as ServiceWorkerControlMessage | undefined;
  const replyPort = event.ports?.[0];
  if (data?.type === 'BIND_MEDIA_SCOPE') {
    const source = event.source;
    if (source && 'id' in source && 'url' in source
      && new URL(source.url).origin === sw.location.origin) {
      mediaScopes.bind(source.id, data.owner, data.epoch);
    }
    return;
  }
  if (data?.type === 'REVOKE_MEDIA_SCOPE') {
    mediaScopes.revoke();
    return;
  }

  if (data?.type === 'GET_VERSION') {
    replyPort?.postMessage({ type: 'VERSION', version });
    return;
  }

  if (data?.type === 'CLEAR_MEDIA_CACHE') {
    // Logout/clear: invalidate in-flight media writes, then drop the cache.
    mediaCacheGeneration += 1;
    mediaScopes.revoke();
    replyPort?.postMessage({ type: 'CLEAR_MEDIA_CACHE_ACK' });
    return;
  }

  if (data?.type === 'SKIP_WAITING') {
    event.waitUntil(
      (async () => {
        await sw.skipWaiting();
        replyPort?.postMessage({ type: 'SKIP_WAITING_ACK', version });
      })()
    );
    return;
  }

  if (data?.type === 'ACTIVE_CONVERSATION') {
    const sourceId = (event.source as Client | null | undefined)?.id;
    if (!sourceId) return;
    const conversationId = typeof data.conversation_id === 'string' ? data.conversation_id.trim() : '';
    if (data.active && conversationId) activeConversationByClient.set(sourceId, conversationId);
    else activeConversationByClient.delete(sourceId);
    return;
  }

  if (data?.type === 'CONVERSATION_OBSERVED') {
    const sourceId = (event.source as Client | null | undefined)?.id;
    if (!sourceId) return;
    pushObservations.record(sourceId, data.conversation_id, data.observed_at);
    event.waitUntil(
      persistPushObservation(sourceId, data.conversation_id, data.observed_at).catch(() => {
        // In-memory correlation still covers the common case when persistence is unavailable.
      }),
    );
  }
});

function parsePushPayload(event: PushEvent): WebPushPayload {
  if (!event.data) return {};
  try {
    return event.data.json() as WebPushPayload;
  } catch {
    return { body: event.data.text() };
  }
}

function notificationIcon(value: unknown): string {
  if (typeof value !== 'string' || value.startsWith('//')) return '/pwa/icon-192.png';
  try {
    const url = new URL(value, sw.location.origin);
    if (url.origin !== sw.location.origin) return '/pwa/icon-192.png';
    return url.href;
  } catch {
    return '/pwa/icon-192.png';
  }
}

function sameOriginTarget(value: unknown): string | null {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    const url = new URL(value, sw.location.origin);
    if (url.origin !== sw.location.origin) return null;
    return url.href;
  } catch {
    return null;
  }
}

function notificationTarget(notification: Notification): string {
  const data = notification.data as { url?: unknown; conversation_id?: unknown } | undefined;
  const dataUrl = sameOriginTarget(data?.url);
  if (dataUrl) return dataUrl;
  if (typeof data?.conversation_id === 'string' && data.conversation_id.trim()) {
    return new URL(`/chat/${encodeURIComponent(data.conversation_id)}`, sw.location.origin).href;
  }
  if (/^conv_[A-Za-z0-9_-]+$/.test(notification.tag || '')) {
    return new URL(`/chat/${encodeURIComponent(notification.tag)}`, sw.location.origin).href;
  }
  return new URL('/chat', sw.location.origin).href;
}

function arrayBufferToUrlBase64(value: ArrayBuffer | null): string | null {
  if (!value) return null;
  const bytes = new Uint8Array(value);
  let raw = '';
  for (const byte of bytes) raw += String.fromCharCode(byte);
  return btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function urlBase64ToArrayBuffer(value: string): ArrayBuffer {
  const padding = '='.repeat((4 - (value.length % 4)) % 4);
  const base64 = (value + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  const output = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) {
    output[i] = raw.charCodeAt(i);
  }
  return output.buffer as ArrayBuffer;
}

async function fetchApplicationServerKey(): Promise<ArrayBuffer | null> {
  try {
    const response = await fetch('/api/v1/push/vapid-public-key', { credentials: 'same-origin' });
    if (!response.ok) return null;
    const payload = await response.json() as { enabled?: boolean; public_key?: string | null };
    if (!payload.enabled || !payload.public_key) return null;
    return urlBase64ToArrayBuffer(payload.public_key);
  } catch {
    return null;
  }
}

/** Returns true when the server reports the endpoint as permanently gone. */
async function uploadPushSubscription(subscription: PushSubscription): Promise<boolean> {
  const json = subscription.toJSON() as {
    endpoint?: string;
    expirationTime?: number | null;
    keys?: { p256dh?: string; auth?: string };
  };
  const endpoint = json.endpoint ?? subscription.endpoint;
  const p256dh = json.keys?.p256dh;
  const auth = json.keys?.auth;
  if (!endpoint || !p256dh || !auth) return false;
  const response = await fetch('/api/v1/push/subscriptions', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      endpoint,
      expirationTime: json.expirationTime ?? null,
      keys: { p256dh, auth },
      platform: 'pwa'
    })
  });
  if (!response.ok) {
    throw new Error('Push subscription upload failed');
  }
  const payload = await response.json().catch(() => null) as { gone?: boolean } | null;
  return payload?.gone === true;
}

sw.addEventListener('pushsubscriptionchange', (event) => {
  const changeEvent = event as ExtendableEvent & { oldSubscription?: PushSubscription | null };
  changeEvent.waitUntil(
    (async () => {
      const existingKey = arrayBufferToUrlBase64(changeEvent.oldSubscription?.options.applicationServerKey ?? null);
      const applicationServerKey = existingKey
        ? urlBase64ToArrayBuffer(existingKey)
        : await fetchApplicationServerKey();
      if (!applicationServerKey) return;
      for (let attempt = 0; attempt < 2; attempt += 1) {
        const subscription = await sw.registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey
        });
        if (!(await uploadPushSubscription(subscription))) return;
        // The browser handed back an endpoint the push service rejected.
        await subscription.unsubscribe().catch(() => false);
      }
    })()
  );
});

function conversationPath(conversationId: string | undefined): string | null {
  if (!conversationId) return null;
  return `/chat/${encodeURIComponent(conversationId)}`;
}

function isForegroundClient(client: WindowClient): boolean {
  return client.focused || client.visibilityState === 'visible';
}

async function hasForegroundClientFor(target: URL, conversationId: string | undefined): Promise<boolean> {
  const targetConversationPath = conversationPath(conversationId);
  const clients = await sw.clients.matchAll({ type: 'window', includeUncontrolled: true });
  return clients.some((client) => {
    const windowClient = client as WindowClient;
    try {
      const url = new URL(windowClient.url);
      if (url.origin !== sw.location.origin) return false;
      if (conversationId && activeConversationByClient.get(windowClient.id) === conversationId) return true;
      if (!isForegroundClient(windowClient)) return false;
      return url.pathname === target.pathname
        || (targetConversationPath !== null && url.pathname === targetConversationPath);
    } catch {
      return false;
    }
  });
}

async function wasPushObserved(
  conversationId: string | undefined,
  occurredAt: string | undefined,
): Promise<boolean> {
  if (!conversationId || !occurredAt) return false;
  const clients = await sw.clients.matchAll({ type: 'window', includeUncontrolled: true });
  const clientIds = clients.map((client) => client.id);
  pushObservations.retainClients(clientIds);
  await restorePushObservations(clientIds).catch(() => {
    // Fall back to the current in-memory and foreground checks.
  });
  return pushObservations.wasObserved(clientIds, conversationId, occurredAt);
}

const SUPPRESSED_NOTIFICATION_TAG = 'cognis-suppressed';

async function showAndDismissSuppressedNotification(title: string): Promise<void> {
  try {
    await sw.registration.showNotification(title, {
      body: '',
      tag: SUPPRESSED_NOTIFICATION_TAG,
      silent: true,
      badge: '/pwa/badge-96.png',
      data: { kind: 'suppressed' },
    });
    const shown = await sw.registration.getNotifications({ tag: SUPPRESSED_NOTIFICATION_TAG });
    for (const notification of shown) notification.close();
  } catch {
    // Best effort; the push event itself still completes.
  }
}

sw.addEventListener('push', (event) => {
  const payload = parsePushPayload(event);
  event.waitUntil(
    (async () => {
      const target = new URL(payload.url || '/chat', sw.location.origin);
      if (
        await wasPushObserved(payload.conversation_id, payload.occurred_at)
        || await hasForegroundClientFor(target, payload.conversation_id)
      ) {
        // The user is already looking at this. Safari/iOS revokes the push
        // subscription after a few pushes that display nothing, so show a
        // silent notification and close it at once instead of skipping it.
        await showAndDismissSuppressedNotification(payload.title || 'Cognis');
        return;
      }
      const notificationOptions: NotificationOptions & {
        actions?: Array<{ action: string; title: string }>;
      } = {
        body: payload.body || 'Cognis needs your attention.',
        icon: notificationIcon(payload.icon),
        badge: '/pwa/badge-96.png',
        tag: payload.tag || 'cognis',
        data: {
          url: `${target.pathname}${target.search}${target.hash}`,
          conversation_id: payload.conversation_id,
          kind: payload.kind || 'notification',
          notification_id: payload.notification_id
        },
        actions: payload.actions,
      };
      await sw.registration.showNotification(payload.title || 'Cognis', notificationOptions);
    })()
  );
});

sw.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    (async () => {
      const notificationData = event.notification.data as {
        notification_id?: unknown;
      } | undefined;
      if (
        (event.action === 'approve' || event.action === 'deny')
        && typeof notificationData?.notification_id === 'string'
      ) {
        const response = await fetch(
          `/api/v1/attention-actions/${encodeURIComponent(notificationData.notification_id)}/resolve`,
          {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({
              expected_revision: 1,
              submission_id: `notification-${event.action}-${notificationData.notification_id}`,
              action: event.action
            })
          }
        ).catch(() => null);
        if (response?.ok) return;
      }
      const target = notificationTarget(event.notification);
      const actionTarget = new URL(target);
      if (event.action) actionTarget.searchParams.set('notificationAction', event.action);
      const resolvedTarget = actionTarget.href;
      const clients = await sw.clients.matchAll({ type: 'window', includeUncontrolled: true });

      for (const client of clients) {
        const windowClient = client as WindowClient;
        try {
          if (new URL(windowClient.url).href !== resolvedTarget) continue;
          await windowClient.focus();
          return;
        } catch {
          // Try the next window client.
        }
      }

      for (const client of clients) {
        const windowClient = client as WindowClient;
        try {
          if (new URL(windowClient.url).origin !== sw.location.origin) continue;
          windowClient.postMessage({ type: 'OPEN_NOTIFICATION_TARGET', url: resolvedTarget });
          const navigated = await windowClient.navigate(resolvedTarget);
          await (navigated ?? windowClient).focus();
          return;
        } catch {
          // Try the next window client.
        }
      }

      await sw.clients.openWindow(resolvedTarget);
    })()
  );
});

/**
 * Returns true if the request must bypass the SW entirely (no caching, no
 * offline fallback). This covers:
 *   - non-GET requests
 *   - WebSocket upgrades and SSE streams
 *   - ALL API calls (so user-specific data is never cached)
 *   - cross-origin requests
 */
function isPassthrough(request: Request, url: URL): boolean {
  if (request.method !== 'GET') return true;

  if (request.headers.get('upgrade') === 'websocket') return true;
  const accept = request.headers.get('accept') ?? '';
  if (accept.includes('text/event-stream')) return true;

  // All /api/** endpoints pass through. Cognis API responses are scoped to
  // the current user via JWT; caching them in a shared browser cache would
  // leak data across user sessions after logout/login on the same device.
  if (url.pathname.startsWith('/api/')) return true;

  // Well-known endpoints: JWKS etc. are public but rotate — passthrough is
  // simpler than caching and doesn't cost anything the browser won't already
  // do with HTTP cache headers.
  if (url.pathname.startsWith('/.well-known/')) return true;

  if (url.origin !== sw.location.origin) return true;

  return false;
}

function isPrecached(url: URL): boolean {
  return PRECACHE_URL_SET.has(url.pathname);
}

/** Content-hashed build output can be cached forever once fetched. */
function isImmutableAsset(url: URL): boolean {
  return url.pathname.startsWith(IMMUTABLE_PREFIX) && !url.search;
}

async function runtimeCacheFirst(request: Request): Promise<Response> {
  try {
    const cache = await openCacheWithTimeout(RUNTIME);
    const cached = await matchCacheWithTimeout(cache, request);
    if (cached) return cached;
  } catch {
    // Treat a wedged CacheStorage as a miss.
  }
  const response = await fetch(request);
  if (response.ok && response.type === 'basic') {
    const copy = response.clone();
    void openCacheWithTimeout(RUNTIME)
      .then((runtime) => runtime.put(request, copy))
      .catch(() => {});
  }
  return response;
}

function rejectAfter<T>(timeoutMs: number, label: string): Promise<T> {
  return new Promise((_resolve, reject) => {
    setTimeout(() => reject(new Error(`${label} timed out after ${Math.round(timeoutMs / 1000)} seconds.`)), timeoutMs);
  });
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, label: string): Promise<T> {
  return Promise.race([promise, rejectAfter<T>(timeoutMs, label)]);
}

async function openCacheWithTimeout(cacheName: string): Promise<Cache> {
  return withTimeout(caches.open(cacheName), CACHE_OPERATION_TIMEOUT_MS, `Opening ${cacheName}`);
}

async function matchCacheWithTimeout(cache: Cache, request: Request | string): Promise<Response | undefined> {
  return withTimeout(cache.match(request), CACHE_OPERATION_TIMEOUT_MS, 'Cache match');
}

async function cacheFirst(request: Request): Promise<Response> {
  try {
    const cache = await openCacheWithTimeout(PRECACHE);
    const cached = await matchCacheWithTimeout(cache, request);
    if (cached) return cached;
  } catch {
    // WebKit PWAs can leave CacheStorage operations pending indefinitely after
    // process resume. Treat cache lookup failure/timeout as a miss and try the
    // network rather than hanging the fetch event.
  }
  try {
    const response = await fetch(request);
    if (response.ok) {
      void openCacheWithTimeout(RUNTIME)
        .then((runtime) => runtime.put(request, response.clone()))
        .catch(() => {});
    }
    return response;
  } catch {
    // If a precached asset is missing locally (shouldn't happen post-install)
    // return a 503 rather than anything misleading.
    return new Response('Offline', { status: 503, statusText: 'Offline' });
  }
}

async function staleWhileRevalidate(request: Request): Promise<Response> {
  let cache: Cache | null = null;
  let cached: Response | undefined;
  try {
    cache = await openCacheWithTimeout(RUNTIME);
    cached = await matchCacheWithTimeout(cache, request);
  } catch {
    cache = null;
    cached = undefined;
  }
  const fetchPromise = fetch(request)
    .then((response) => {
      if (response.ok && cache) void cache.put(request, response.clone()).catch(() => {});
      return response;
    })
    .catch(() => cached);
  return cached ?? (await fetchPromise) ?? new Response('', { status: 504 });
}

// Viewed chat media (images, signed artifact files). Content is immutable per
// object id, so it is cached by path (signatures in the query rotate) for
// instant and offline re-display. The page wipes this cache on logout.
const MEDIA_CACHE = 'cognis-media-v1';
let mediaCacheGeneration = 0;
const MEDIA_CACHE_MAX_ENTRIES = 200;
const MEDIA_CACHE_MAX_BYTES = 10 * 1024 * 1024;
const MEDIA_PATH = /^\/api\/v1\/(?:images\/[^/]+$|artifacts\/(?:content|view)\/)/;

function isCacheableMediaRequest(request: Request, url: URL): boolean {
  return request.method === 'GET'
    && url.origin === sw.location.origin
    && MEDIA_PATH.test(url.pathname)
    && !request.headers.has('range');
}

function mediaCacheKey(url: URL): string {
  return `${url.origin}${url.pathname}`;
}

async function trimMediaCache(cache: Cache): Promise<void> {
  const keys = await cache.keys();
  const excess = keys.length - MEDIA_CACHE_MAX_ENTRIES;
  // CacheStorage keys are returned in insertion order: drop the oldest.
  for (let index = 0; index < excess; index += 1) await cache.delete(keys[index]);
}

async function mediaCacheFirst(request: Request, url: URL, clientId: string): Promise<Response> {
  const scope = mediaScopes.scope(clientId);
  // Unknown-owner caches are preserved but never read, including after restart.
  if (!scope) return fetch(request);
  const key = new Request(url.href, { method: 'GET' });
  const cacheName = mediaScopes.cache(scope);
  const generation = mediaCacheGeneration;
  try {
    const cache = await openCacheWithTimeout(cacheName);
    const cached = await matchCacheWithTimeout(cache, key);
    if (cached && mediaScopes.current(clientId, scope)) return cached;
  } catch {
    // Treat a wedged CacheStorage as a miss.
  }
  const response = await fetch(request);
  const contentType = response.headers.get('content-type') ?? '';
  const length = Number(response.headers.get('content-length') ?? '0');
  if (
    response.status === 200
    && response.type === 'basic'
    && /^(?:image|audio)\//.test(contentType)
    && (!length || length <= MEDIA_CACHE_MAX_BYTES)
  ) {
    const copy = response.clone();
    void (async () => {
      try {
        if (generation !== mediaCacheGeneration || !mediaScopes.current(clientId, scope)) return;
        const cache = await openCacheWithTimeout(cacheName);
        if (generation !== mediaCacheGeneration || !mediaScopes.current(clientId, scope)) return;
        await cache.put(key, copy);
        if (generation !== mediaCacheGeneration || !mediaScopes.current(clientId, scope)) {
          // A clear raced this write; undo it.
          await cache.delete(key);
          return;
        }
        await trimMediaCache(cache);
      } catch {
        // Quota or storage errors only cost a later re-download.
      }
    })();
  }
  return response;
}

sw.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (isCacheableMediaRequest(event.request, url)) {
    event.respondWith(mediaCacheFirst(event.request, url, event.clientId));
    return;
  }
  if (isPassthrough(event.request, url)) return;

  // Precached app shell + build assets.
  if (isPrecached(url)) {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  // Other hashed build output (images, fonts, workers): cache on first use.
  if (isImmutableAsset(url)) {
    event.respondWith(runtimeCacheFirst(event.request));
    return;
  }

  // Static-looking images/fonts: stale-while-revalidate.
  if (/\.(?:png|jpg|jpeg|webp|avif|svg|gif|ico|woff2?)$/i.test(url.pathname)) {
    event.respondWith(staleWhileRevalidate(event.request));
    return;
  }

  // Navigation requests (SPA): try network first; fall back to precached
  // shell so the app still boots offline. Non-navigation requests fall
  // through untouched.
  if (event.request.mode === 'navigate') {
    event.respondWith(
      (async () => {
        try {
          return await withTimeout(fetch(event.request), NAVIGATION_FETCH_TIMEOUT_MS, 'Navigation fetch');
        } catch {
          try {
            const cache = await openCacheWithTimeout(PRECACHE);
            const shell =
              (await matchCacheWithTimeout(cache, '/index.html')) ??
              (await matchCacheWithTimeout(cache, '/')) ??
              (await withTimeout(caches.match('/index.html'), CACHE_OPERATION_TIMEOUT_MS, 'Global shell cache match'));
            if (shell) return shell;
          } catch {
            // If CacheStorage itself is wedged, do not keep the navigation
            // request pending; return an explicit offline response.
          }
          return new Response('Offline', { status: 503 });
        }
      })()
    );
  }
});

export {};
