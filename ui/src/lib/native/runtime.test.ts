import { afterEach, describe, expect, it, vi } from 'vitest';
import { get, writable } from 'svelte/store';
import type { AuthState } from '$lib/stores/auth';

const stores = vi.hoisted(() => ({ callbacks: [] as Array<() => void> }));
vi.mock('./notifications', () => ({ installResidentNotifications: () => ({ review: vi.fn(), stop: vi.fn() }) }));
vi.mock('./catalogue', () => ({ installAgentCatalogue: () => () => {}, nativeAgents: writable([]) }));
const authStore = writable<AuthState>({ status: 'anonymous', initialized: true, user: null, expiresAt: null, error: null });
const workspace = writable<{
  owner: string | null;
  entries: Array<{ window: { entityId: string; agentId: string; title: string } }>;
  agents: Array<{ agentId: string; homeConversationId?: string }>;
}>({ owner: null, entries: [], agents: [] });
const agents = writable([]);
const conversations = writable({});
const background = writable([]);
const socket = writable({ status: 'idle' });
vi.mock('$lib/stores/auth', () => ({ auth: { subscribe: (...args: Parameters<typeof authStore.subscribe>) => authStore.subscribe(...args) } }));
vi.mock('$lib/ws/client', () => ({ wsState: { subscribe: (...args: Parameters<typeof socket.subscribe>) => socket.subscribe(...args) }, wsClient: { reconnectNow: vi.fn() } }));
vi.mock('$lib/dashboard/conversation-workspace', () => ({
  conversationWorkspace: { subscribe: (...args: Parameters<typeof workspace.subscribe>) => workspace.subscribe(...args), snapshot: () => get(workspace) },
  retainedConversationId: (window: { entityId: string }) => window.entityId
}));
vi.mock('$lib/dashboard/conversation-workspace-runtime', () => ({
  pinnedAgents: { subscribe: (...args: Parameters<typeof agents.subscribe>) => agents.subscribe(...args) },
  pinnedConversations: { subscribe: (...args: Parameters<typeof conversations.subscribe>) => conversations.subscribe(...args) },
  pinnedBackgroundWork: { subscribe: (...args: Parameters<typeof background.subscribe>) => background.subscribe(...args) }
}));
import { installNativeRuntime } from './runtime';
import { wsClient } from '$lib/ws/client';

const generation = '8d6feafb-2aac-4b41-ac82-42b2314563bb';
afterEach(() => {
  stores.callbacks.forEach((stop) => stop());
  stores.callbacks.length = 0;
  delete window.__cognisNative;
  delete window.webkit;
  workspace.set({ owner: null, entries: [], agents: [] });
  authStore.set({ status: 'anonymous', initialized: true, user: null, expiresAt: null, error: null });
  vi.useRealTimers();
  document.getElementById('appearance-test-palette')?.remove();
  delete document.documentElement.dataset.resolvedTheme;
});

describe('native runtime lifecycle', () => {
  it('publishes literal chrome appearance on resolved-theme changes and deduplicates unchanged updates', async () => {
    window.__cognisNative = { version: 1, generation, server: window.location.origin };
    const send = vi.fn();
    window.webkit = { messageHandlers: { cognis: { postMessage: send } } };
    const style = document.createElement('style');
    style.id = 'appearance-test-palette';
    style.textContent = ':root { --app-chrome-bg: #edf2f5; color-scheme: light; } :root[data-resolved-theme="dark"] { --app-chrome-bg: #07111a; color-scheme: dark; }';
    document.head.appendChild(style);
    const stop = installNativeRuntime(vi.fn().mockResolvedValue(undefined));
    stores.callbacks.push(stop);
    expect(send).toHaveBeenCalledWith(expect.objectContaining({
      type: 'appearance', payload: { theme: 'light', background: '#edf2f5' }
    }));
    document.documentElement.dataset.resolvedTheme = 'dark';
    await Promise.resolve();
    expect(send).toHaveBeenCalledWith(expect.objectContaining({
      type: 'appearance', payload: { theme: 'dark', background: '#07111a' }
    }));
    const count = send.mock.calls.filter(([message]) => message.type === 'appearance').length;
    document.documentElement.dataset.resolvedTheme = 'dark';
    await Promise.resolve();
    expect(send.mock.calls.filter(([message]) => message.type === 'appearance')).toHaveLength(count);
    stop();
    document.documentElement.dataset.resolvedTheme = 'light';
    await Promise.resolve();
    expect(send.mock.calls.filter(([message]) => message.type === 'appearance')).toHaveLength(count);
  });
  it('publishes updated literal chrome for a same-mode family change', async () => {
    window.__cognisNative = { version: 1, generation, server: window.location.origin };
    const send = vi.fn();
    window.webkit = { messageHandlers: { cognis: { postMessage: send } } };
    const style = document.createElement('style');
    style.id = 'appearance-test-palette';
    style.textContent = ':root { --app-chrome-bg: #edf2f5; color-scheme: light; } :root[data-theme-family="paper"] { --app-chrome-bg: #eeeadd; }';
    document.head.appendChild(style);
    document.documentElement.dataset.themeFamily = 'porcelain';
    const stop = installNativeRuntime(vi.fn().mockResolvedValue(undefined));
    stores.callbacks.push(stop);
    document.documentElement.dataset.themeFamily = 'paper';
    await Promise.resolve();
    expect(send).toHaveBeenLastCalledWith(expect.objectContaining({
      type: 'appearance', payload: { theme: 'light', background: '#eeeadd' }
    }));
    stop();
    delete document.documentElement.dataset.themeFamily;
  });

  it('projects resolved agent homes once from the current web owner and ignores unresolved pins', async () => {
    vi.useFakeTimers();
    window.__cognisNative = { version: 1, generation, server: window.location.origin };
    const send = vi.fn();
    window.webkit = { messageHandlers: { cognis: { postMessage: send } } };
    const email = 'mac-companion@cognis.test';
    authStore.set({ status: 'authenticated', initialized: true,
      user: { email } as AuthState['user'], expiresAt: null, error: null });
    workspace.set({ owner: email, entries: [],
      agents: [{ agentId: 'agent_mac', homeConversationId: 'conv_mac' }, { agentId: 'agent_unresolved' }] });
    stores.callbacks.push(installNativeRuntime(vi.fn().mockResolvedValue(undefined)));
    expect(send).toHaveBeenLastCalledWith(expect.objectContaining({
      type: 'snapshot', payload: expect.objectContaining({
        pins: [expect.objectContaining({ conversationId: 'conv_mac', agentId: 'agent_mac' })]
      })
    }));
    workspace.update((state) => ({ ...state, entries: [{
      window: { entityId: 'conv_mac', agentId: 'agent_mac', title: 'Retained conversation' }
    }] }));
    await vi.runAllTimersAsync();
    expect(send.mock.lastCall?.[0].payload.pins).toHaveLength(1);
    workspace.update((state) => ({ ...state, owner: 'other@cognis.test' }));
    await vi.runAllTimersAsync();
    expect(send.mock.lastCall?.[0].payload.pins).toEqual([]);
  });

  it('fences commands by generation and removes listeners on unmount', async () => {
    vi.useFakeTimers();
    window.__cognisNative = { version: 1, generation, server: window.location.origin };
    const send = vi.fn();
    window.webkit = { messageHandlers: { cognis: { postMessage: send } } };
    const navigate = vi.fn().mockResolvedValue(undefined);
    const stop = installNativeRuntime(navigate);
    stores.callbacks.push(stop);
    window.__cognisNativeReceive?.({ version: 1, generation: 'old', type: 'navigate', path: '/chat/new' });
    window.__cognisNativeReceive?.({ version: 2, generation, type: 'navigate', path: '/chat/new' });
    expect(navigate).not.toHaveBeenCalled();
    window.__cognisNativeReceive?.({ version: 1, generation, type: 'navigate', path: '/chat/new' });
    expect(navigate).toHaveBeenCalledExactlyOnceWith('/chat/new');
    stop();
    expect(window.__cognisNativeReceive).toBeUndefined();
    const count = send.mock.calls.length;
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await vi.runAllTimersAsync();
    expect(send).toHaveBeenCalledTimes(count);
  });

  it('publishes an immediate empty lifecycle fence on sign-out', () => {
    vi.useFakeTimers();
    window.__cognisNative = { version: 1, generation, server: window.location.origin };
    const send = vi.fn();
    window.webkit = { messageHandlers: { cognis: { postMessage: send } } };
    const stop = installNativeRuntime(vi.fn().mockResolvedValue(undefined));
    stores.callbacks.push(stop);
    const state: AuthState = { status: 'authenticated', initialized: true,
      user: { email: 'mac-companion@cognis.test' } as AuthState['user'], expiresAt: null, error: null };
    authStore.set(state);
    send.mockClear();
    authStore.set({ ...state, status: 'anonymous', user: null });
    expect(send).toHaveBeenCalledWith(expect.objectContaining({
      type: 'snapshot', payload: expect.objectContaining({ authenticated: false, pins: [] })
    }));
  });
  it('uses the existing socket owner on wake and rejects stale/offline wake commands', () => {
    vi.useFakeTimers();
    window.__cognisNative = { version: 1, generation, server: window.location.origin };
    window.webkit = { messageHandlers: { cognis: { postMessage: vi.fn() } } };
    const state: AuthState = { status: 'authenticated', initialized: true,
      user: { email: 'mac-companion@cognis.test' } as AuthState['user'], expiresAt: null, error: null };
    authStore.set(state);
    const navigate = vi.fn().mockResolvedValue(undefined);
    stores.callbacks.push(installNativeRuntime(navigate));
    vi.mocked(wsClient.reconnectNow).mockClear();
    window.__cognisNativeReceive?.({ version: 1, generation, type: 'resume' });
    expect(wsClient.reconnectNow).toHaveBeenCalledOnce();
    expect(navigate).not.toHaveBeenCalled();
    window.__cognisNativeReceive?.({ version: 1, generation: 'prior-generation', type: 'resume' });
    authStore.set({ ...state, offline: true });
    window.__cognisNativeReceive?.({ version: 1, generation, type: 'resume' });
    expect(wsClient.reconnectNow).toHaveBeenCalledOnce();
  });
});
