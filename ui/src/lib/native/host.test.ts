import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  hostAllowsObservation, nativeConfiguration, openNativeConversationWindow, postNative, receiveNativeVisibility
} from './host';

const generation = '8d6feafb-2aac-4b41-ac82-42b2314563bb';
afterEach(() => {
  delete window.__cognisNative;
  delete window.webkit;
  vi.restoreAllMocks();
});

describe('native host capability boundary', () => {
  it('keeps the browser path inert and observable', () => {
    expect(nativeConfiguration()).toBeNull();
    expect(hostAllowsObservation()).toBe(true);
    expect(() => postNative('dismiss', {})).not.toThrow();
  });

  it('requires matching trusted origin, protocol and generation shape', () => {
    for (const server of ['http://remote.test', 'https://remote.test', 'file:///tmp/ui', 'http://user:pass@localhost']) {
      window.__cognisNative = { version: 1, generation, server };
      expect(nativeConfiguration()).toBeNull();
    }
    window.__cognisNative = { version: 1, generation, server: window.location.origin };
    expect(nativeConfiguration()).not.toBeNull();
    window.__cognisNative = { version: 1, generation: 'old', server: window.location.origin };
    expect(nativeConfiguration()).toBeNull();
  });

  it('scopes messages and rejects oversized state', () => {
    const send = vi.fn();
    window.__cognisNative = { version: 1, generation, server: window.location.origin };
    window.webkit = { messageHandlers: { cognis: { postMessage: send } } };
    postNative('dismiss', {});
    expect(send).toHaveBeenCalledExactlyOnceWith({ version: 1, generation, type: 'dismiss', payload: {} });
    postNative('snapshot', { text: 'x'.repeat(525_000) });
    expect(send).toHaveBeenCalledTimes(1);
    postNative('notification', { text: 'x'.repeat(33_000) });
    expect(send).toHaveBeenCalledTimes(1);
    postNative('snapshot', { agents: Array.from({ length: 500 }, (_, index) => ({
      agentId: `agent_${index}`, name: 'Synthetic catalogue agent',
    })) });
    expect(send).toHaveBeenCalledTimes(2);
  });

  it('never treats a hidden or unfocused resident document as observed', () => {
    window.__cognisNative = { version: 1, generation, server: window.location.origin };
    receiveNativeVisibility(false, false);
    expect(hostAllowsObservation()).toBe(false);
    receiveNativeVisibility(true, false);
    expect(hostAllowsObservation()).toBe(false);
    receiveNativeVisibility(true, true);
    expect(hostAllowsObservation()).toBe(true);
    receiveNativeVisibility(false, true);
    expect(hostAllowsObservation()).toBe(false);
  });
  it('uses the scoped Mac command without offering a browser fallback, even for a rejected ID', () => {
    const send = vi.fn(), open = vi.spyOn(window, 'open');
    expect(openNativeConversationWindow('conv_window')).toBe(false);
    window.__cognisNative = { version: 1, generation, server: window.location.origin };
    window.webkit = { messageHandlers: { cognis: { postMessage: send } } };
    expect(openNativeConversationWindow('conv_window')).toBe(true);
    expect(send).toHaveBeenCalledExactlyOnceWith({
      version: 1, generation, type: 'open-window', payload: { conversationId: 'conv_window' }
    });
    expect(openNativeConversationWindow('https://untrusted.test')).toBe(true);
    expect(send).toHaveBeenCalledTimes(1);
    expect(open).not.toHaveBeenCalled();
  });
});
