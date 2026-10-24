/**
 * Browser notification utilities.
 *
 * Uses standard Web Push for installed PWAs, with a tab-local Notification
 * fallback while the app is open.
 */

import { api } from '$lib/api/client';
import { auth } from '$lib/stores/auth';
import { isNativeHost } from '$lib/native/host';

const PERMISSION_KEY = 'cognis_notification_permission_asked';
const WEB_PUSH_ENABLED_KEY = 'cognis_web_push_enabled';
const WEB_PUSH_PROMPT_DISMISSED_KEY = 'cognis_web_push_prompt_dismissed';
// The user's intent to receive push on this device. Unlike the enabled flag
// (current health), it survives the browser or push service dropping the
// subscription, so the app can silently resubscribe instead of asking again.
// Cleared only by an explicit disable or logout.
const WEB_PUSH_WANTED_KEY = 'cognis_web_push_wanted';

/** Whether the browser supports the Notification API. */
export function isSupported(): boolean {
  return !isNativeHost() && typeof window !== 'undefined' && 'Notification' in window;
}

/** Whether this browser can subscribe to Web Push from the current context. */
export function isWebPushSupported(): boolean {
  return (
    !isNativeHost() && typeof window !== 'undefined'
    && 'serviceWorker' in navigator
    && 'PushManager' in window
    && 'Notification' in window
  );
}

/** Whether the app is running as an installed standalone PWA. */
export function isStandaloneDisplay(): boolean {
  if (typeof window === 'undefined') return false;
  return (
    window.matchMedia?.('(display-mode: standalone)').matches
    || (window.navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

/** iOS Safari can only expose Web Push from a Home Screen web app. */
export function needsIosHomeScreenInstall(): boolean {
  if (typeof window === 'undefined') return false;
  const ua = navigator.userAgent || '';
  const isIos = /iPad|iPhone|iPod/.test(ua) && !('MSStream' in window);
  const isSafari = /Safari/i.test(ua) && !/CriOS|FxiOS|EdgiOS|OPiOS/i.test(ua);
  return isIos && isSafari && !isStandaloneDisplay() && !isWebPushSupported();
}

/** Current permission state. */
export function permissionState(): NotificationPermission | 'unsupported' {
  if (!isSupported()) return 'unsupported';
  return Notification.permission;
}

/** Whether we have permission to show notifications. */
export function isGranted(): boolean {
  return isSupported() && Notification.permission === 'granted';
}

/** Whether we've already asked the user (avoid repeated prompts). */
export function hasAskedPermission(): boolean {
  if (typeof localStorage === 'undefined') return false;
  return localStorage.getItem(PERMISSION_KEY) === 'true';
}

export function hasEnabledWebPush(): boolean {
  if (typeof localStorage === 'undefined') return false;
  return localStorage.getItem(WEB_PUSH_ENABLED_KEY) === 'true';
}

// Bumped by an explicit disable; reconciliations started earlier stop.
let pushIntentGeneration = 0;

function currentUserEmail(): string | null {
  return auth.getSnapshot().user?.email?.trim().toLowerCase() || null;
}

/**
 * Whether the signed-in user opted in to push on this device. The intent is
 * bound to the user who enabled it, so it never carries over to another
 * account (logout and account switches also clear it).
 */
export function wantsWebPush(): boolean {
  if (typeof localStorage === 'undefined') return false;
  const owner = localStorage.getItem(WEB_PUSH_WANTED_KEY);
  const user = currentUserEmail();
  if (owner) return Boolean(user) && owner === user;
  // Devices enabled before the intent key existed count as wanting push.
  return hasEnabledWebPush();
}

function setWebPushWanted(wanted: boolean): void {
  if (typeof localStorage === 'undefined') return;
  const user = currentUserEmail();
  if (wanted && user) localStorage.setItem(WEB_PUSH_WANTED_KEY, user);
  else localStorage.removeItem(WEB_PUSH_WANTED_KEY);
}

export function hasDismissedWebPushPrompt(): boolean {
  if (typeof localStorage === 'undefined') return false;
  return localStorage.getItem(WEB_PUSH_PROMPT_DISMISSED_KEY) === 'true';
}

function setWebPushEnabled(enabled: boolean): void {
  if (typeof localStorage === 'undefined') return;
  if (enabled) localStorage.setItem(WEB_PUSH_ENABLED_KEY, 'true');
  else localStorage.removeItem(WEB_PUSH_ENABLED_KEY);
}

export function setWebPushPromptDismissed(dismissed: boolean): void {
  if (typeof localStorage === 'undefined') return;
  if (dismissed) localStorage.setItem(WEB_PUSH_PROMPT_DISMISSED_KEY, 'true');
  else localStorage.removeItem(WEB_PUSH_PROMPT_DISMISSED_KEY);
}

/** Whether the user is not actively focused on this browser context. */
export function shouldNotifyWhenUnfocused(): boolean {
  if (typeof document === 'undefined') return false;
  return document.visibilityState !== 'visible' || !document.hasFocus();
}

/**
 * Request notification permission from the user.
 * Returns the resulting permission state.
 * Only asks once — subsequent calls return the cached state.
 */
export async function requestPermission(): Promise<NotificationPermission | 'unsupported'> {
  if (!isSupported()) return 'unsupported';
  if (Notification.permission !== 'default') return Notification.permission;
  try {
    const result = await Notification.requestPermission();
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(PERMISSION_KEY, 'true');
    }
    return result;
  } catch {
    return 'denied';
  }
}

function urlBase64ToArrayBuffer(value: string): ArrayBuffer {
  const padding = '='.repeat((4 - (value.length % 4)) % 4);
  const base64 = (value + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = window.atob(base64);
  const output = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) {
    output[i] = raw.charCodeAt(i);
  }
  return output.buffer as ArrayBuffer;
}

function arrayBufferToUrlBase64(value: ArrayBuffer | null): string | null {
  if (!value) return null;
  const bytes = new Uint8Array(value);
  let raw = '';
  for (const byte of bytes) raw += String.fromCharCode(byte);
  return window.btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

export interface EnableWebPushResult {
  ok: boolean;
  status: 'enabled' | 'unsupported' | 'denied' | 'unavailable' | 'error';
  message: string;
}

interface SubscriptionJson {
  endpoint?: string;
  expirationTime?: number | null;
  keys?: { p256dh?: string; auth?: string };
}

/** Upload a browser subscription; returns the server's verdict. */
async function uploadSubscription(subscription: PushSubscription): Promise<'ok' | 'gone' | 'invalid'> {
  const json = subscription.toJSON() as SubscriptionJson;
  const endpoint = json.endpoint ?? subscription.endpoint;
  const p256dh = json.keys?.p256dh;
  const auth = json.keys?.auth;
  if (!endpoint || !p256dh || !auth) return 'invalid';
  const response = await api.push.subscribe({
    endpoint,
    expirationTime: json.expirationTime ?? null,
    keys: { p256dh, auth },
    platform: isStandaloneDisplay() ? 'pwa' : 'browser'
  });
  return response.gone ? 'gone' : 'ok';
}

/**
 * Ensure this browser holds a live subscription registered with the server.
 * Replaces subscriptions with a stale key or an endpoint the push service has
 * declared gone (iOS revokes subscriptions; the old endpoint stays readable
 * locally but never delivers again).
 */
async function ensureRegisteredSubscription(
  registration: ServiceWorkerRegistration,
  publicKey: string,
  stillWanted: () => boolean = () => true,
): Promise<PushSubscription | null> {
  let subscription = await registration.pushManager.getSubscription();
  if (!stillWanted()) return null;
  const existingKey = arrayBufferToUrlBase64(subscription?.options.applicationServerKey ?? null);
  if (subscription && existingKey && existingKey !== publicKey) {
    await subscription.unsubscribe();
    subscription = null;
  }
  for (let attempt = 0; attempt < 2; attempt += 1) {
    subscription ??= await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToArrayBuffer(publicKey)
    });
    // Checked synchronously right before the upload (which uses the current
    // session cookie): logout, disable, or an account switch while we were
    // waiting must not register this device for anyone.
    if (!stillWanted()) return null;
    const verdict = await uploadSubscription(subscription);
    if (verdict === 'ok') return subscription;
    if (verdict === 'invalid') return null;
    // Gone: drop the dead endpoint and create a fresh one once.
    await subscription.unsubscribe().catch(() => false);
    subscription = null;
  }
  return null;
}

/** Subscribe this browser to native Web Push notifications. */
export async function enableWebPush(): Promise<EnableWebPushResult> {
  if (!isWebPushSupported()) {
    if (needsIosHomeScreenInstall()) {
      return {
        ok: false,
        status: 'unsupported',
        message: 'On iPhone or iPad, add Cognis to the Home Screen and open it there before enabling notifications.'
      };
    }
    return { ok: false, status: 'unsupported', message: 'This browser does not support Web Push notifications.' };
  }

  try {
    const permission = await requestPermission();
    if (permission !== 'granted') {
      return { ok: false, status: 'denied', message: 'Notifications were not allowed.' };
    }

    const keyResponse = await api.push.vapidPublicKey();
    if (!keyResponse.enabled || !keyResponse.public_key) {
      return {
        ok: false,
        status: 'unavailable',
        message: keyResponse.reason ?? 'Web Push is not configured on this Cognis server.'
      };
    }

    const registration = await navigator.serviceWorker.ready;
    const subscription = await ensureRegisteredSubscription(registration, keyResponse.public_key);
    if (!subscription) {
      return { ok: false, status: 'error', message: 'Browser returned an unusable push subscription.' };
    }
    const verifiedSubscription = await registration.pushManager.getSubscription();
    if (!verifiedSubscription) {
      setWebPushEnabled(false);
      return {
        ok: false,
        status: 'error',
        message: 'Browser did not retain the push subscription. Try reloading Cognis and enabling notifications again.'
      };
    }
    setWebPushEnabled(true);
    setWebPushWanted(true);
    setWebPushPromptDismissed(true);
    return { ok: true, status: 'enabled', message: 'Native notifications are enabled.' };
  } catch (error) {
    return {
      ok: false,
      status: 'error',
      message: error instanceof Error ? error.message : 'Unable to enable notifications.'
    };
  }
}

/**
 * Reconcile a previously enabled browser subscription with the backend.
 *
 * Browsers can drop PushManager subscriptions and development databases can be
 * recreated. Keep the local enabled flag truthful so notification fallback and
 * prompts do not assume Web Push is healthy when no usable subscription exists.
 */
export async function reconcileWebPushSubscription(): Promise<boolean> {
  if (!wantsWebPush()) return false;
  if (!isWebPushSupported() || !isGranted()) {
    setWebPushEnabled(false);
    return false;
  }
  const owner = currentUserEmail();
  const generation = pushIntentGeneration;
  // Same user, intent still present (not disabled/logged out meanwhile).
  const stillWanted = () => (
    generation === pushIntentGeneration
    && wantsWebPush()
    && currentUserEmail() === owner
  );

  let registration: ServiceWorkerRegistration | null = null;
  try {
    const keyResponse = await api.push.vapidPublicKey();
    if (!keyResponse.enabled || !keyResponse.public_key) return hasEnabledWebPush();
    registration = await navigator.serviceWorker.ready;
    // Permission is already granted, so a dropped or revoked subscription is
    // replaced silently instead of asking the user to enable it again.
    const subscription = await ensureRegisteredSubscription(
      registration,
      keyResponse.public_key,
      stillWanted,
    );
    if (!stillWanted()) return false;
    setWebPushEnabled(Boolean(subscription));
    if (subscription && !localStorage.getItem(WEB_PUSH_WANTED_KEY)) setWebPushWanted(true);
    return Boolean(subscription);
  } catch {
    // Network trouble, or a browser that needs a user gesture to subscribe.
    // Keep the intent (retried on the next reconcile) but report health
    // truthfully so Settings offers Enable when no subscription exists.
    const present = registration
      ? await registration.pushManager.getSubscription().catch(() => null)
      : undefined;
    if (present === null && stillWanted()) setWebPushEnabled(false);
    return hasEnabledWebPush();
  }
}

export async function disableWebPushForCurrentDevice(): Promise<boolean> {
  // An explicit disable ends the intent immediately and on every path (even
  // if the browser already dropped the subscription) and cancels in-flight
  // reconciliations, so nothing can recreate the subscription afterwards.
  pushIntentGeneration += 1;
  setWebPushWanted(false);
  setWebPushEnabled(false);
  if (!isWebPushSupported()) {
    return false;
  }

  try {
    const registration = await navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      setWebPushEnabled(false);
      return false;
    }
    if (subscription.endpoint) {
      await api.push.unsubscribe(subscription.endpoint).catch(() => undefined);
    }
    const removed = await subscription.unsubscribe();
    if (removed) {
      setWebPushEnabled(false);
      setWebPushPromptDismissed(false);
    }
    return removed;
  } catch {
    return false;
  }
}

/**
 * Show a browser notification.
 *
 * @param title - Notification title (e.g. agent name)
 * @param body - Notification body text
 * @param conversationId - If provided, clicking the notification navigates to this conversation
 */
export function showNotification(
  title: string,
  body: string,
  conversationId?: string,
): void {
  if (!isGranted()) return;
  try {
    const notification = new Notification(title, {
      body,
      icon: '/pwa/icon-192.png',
      tag: conversationId ?? 'cognis',
      // Reuse the same tag to avoid notification spam for the same conversation
    });
    notification.onclick = () => {
      window.focus();
      if (conversationId) {
        window.location.href = `/chat/${conversationId}`;
      }
      notification.close();
    };
    // Auto-close after 10 seconds
    setTimeout(() => notification.close(), 10_000);
  } catch {
    // Notification constructor can throw in some environments
  }
}

/**
 * Show a notification for a new message in a conversation the user isn't viewing.
 * Only shows if the document is hidden or the user is on a different conversation.
 */
export function notifyIfHidden(
  title: string,
  body: string,
  conversationId: string,
  activeConversationId: string | null,
): void {
  if (activeConversationId && conversationId === activeConversationId) return;
  if (!shouldNotifyWhenUnfocused()) return;
  if (hasEnabledWebPush()) return;
  showNotification(title, body, conversationId);
}
