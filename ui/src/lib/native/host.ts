import { writable } from 'svelte/store';
/** Versioned capability boundary; browsers never acquire native capabilities. */
export interface NativeConfiguration {
  version: 1;
  generation: string;
  server: string;
  surface?: 'main' | 'pinned' | 'rail' | 'conversation';
}

declare global {
  interface Window {
    __cognisNative?: NativeConfiguration;
    __cognisNativeReceive?: (command: unknown) => void;
    webkit?: { messageHandlers?: { cognis?: { postMessage: (value: unknown) => void } } };
  }
}

export function nativeConfiguration(): NativeConfiguration | null {
  if (typeof window === 'undefined' || window.top !== window) return null;
  const config = window.__cognisNative;
  if (config?.version !== 1 || typeof config.generation !== 'string'
    || !/^[0-9a-f-]{36}$/i.test(config.generation)) return null;
  try {
    const url = new URL(config.server);
    const local = ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);
    if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && local))
      || url.username || url.password || url.origin !== window.location.origin
      || url.pathname !== '/' || url.search || url.hash) return null;
    return config;
  } catch { return null; }
}

export function isNativeHost(): boolean { return nativeConfiguration() !== null; }
export function isWorkspaceReplica(): boolean {
  const config = nativeConfiguration();
  return !!config?.surface && config.surface !== 'main';
}

export function postNative(type: 'snapshot' | 'route' | 'dismiss' | 'avatar' | 'appearance' | 'open-main' | 'open-window' | 'notification-scope' | 'notification' | 'notification-review' | 'notification-settings' | 'workspace' | 'rail' | 'panel-state', payload: unknown): void {
  const config = nativeConfiguration();
  if (!config) return;
  const message = { version: 1, generation: config.generation, type, payload };
  if (JSON.stringify(message).length > (['workspace', 'snapshot'].includes(type) ? 524_288 : 32_768)) return;
  window.webkit?.messageHandlers?.cognis?.postMessage(message);
}

/** A Mac chat window is an identifier-only native capability, not a URL opener. */
export function openNativeConversationWindow(conversationId: string): boolean {
  if (!isNativeHost()) return false;
  if (/^[A-Za-z0-9_-]{1,160}$/.test(conversationId)) postNative('open-window', { conversationId });
  return true;
}

let nativeVisible = false;
let nativeFocused = false;
export const nativeVisibility = writable({ visible: false, focused: false });

/** Read receipts require a visible, focused native surface, not a resident document. */
export function hostAllowsObservation(): boolean {
  return !isNativeHost() || (nativeVisible && nativeFocused);
}

export function receiveNativeVisibility(visible: boolean, focused: boolean): void {
  const wasVisible = nativeVisible, wasFocused = nativeFocused;
  nativeVisible = visible;
  nativeFocused = visible && focused;
  nativeVisibility.set({ visible: nativeVisible, focused: nativeFocused });
  if (nativeVisible !== wasVisible) document.dispatchEvent(new Event('visibilitychange'));
  if (nativeFocused !== wasFocused) window.dispatchEvent(new Event(nativeFocused ? 'focus' : 'blur'));
}
