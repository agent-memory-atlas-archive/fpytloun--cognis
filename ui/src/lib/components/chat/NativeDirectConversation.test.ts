import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';
import { cleanup, render, screen } from '@testing-library/svelte';
import type { AuthState } from '$lib/stores/auth';

const mocks = vi.hoisted(() => ({ detail: vi.fn(), resolve: vi.fn(), read: vi.fn(), send: vi.fn() }));
const state = writable<AuthState>({ status: 'anonymous', initialized: true, user: null, expiresAt: null, error: null });
const visibility = writable({ visible: true, focused: true });
vi.mock('$lib/stores/auth', () => ({ auth: { subscribe: (...args: Parameters<typeof state.subscribe>) => state.subscribe(...args) } }));
vi.mock('$lib/native/host', () => ({ postNative: mocks.send, isWorkspaceReplica: () => true, isNativeHost: () => true,
  nativeVisibility: { subscribe: (...args: Parameters<typeof visibility.subscribe>) => visibility.subscribe(...args) } }));
vi.mock('$lib/api/client', () => ({ api: {
  agents: { detail: mocks.detail }, conversations: { resolve: mocks.resolve, markRead: mocks.read },
}, asApiError: (error: Error) => error }));
vi.mock('$lib/components/chat-v2/CompactConversationChat.svelte', () => import('./NativeDirectConversation.test-fixture.svelte'));
import NativeDirectConversation from './NativeDirectConversation.svelte';
import { conversationWorkspace } from '$lib/dashboard/conversation-workspace';

beforeEach(() => {
  vi.resetAllMocks();
  mocks.detail.mockResolvedValue({ agent_id: 'agent_fixture', name: 'Synthetic agent', is_system: false, disabled: false });
  mocks.resolve.mockResolvedValue({ conversation_id: 'conv_existing', context: { type: 'web' } });
  state.set({ status: 'authenticated', initialized: true, user: { email: 'native@fixture.invalid' } as AuthState['user'],
    expiresAt: null, error: null });
});
afterEach(cleanup);

it('opens an unpinned agent through the canonical resolver without pinning; keeps a mounted chat', async () => {
  const before = conversationWorkspace.snapshot();
  const view = render(NativeDirectConversation, { agentId: 'agent_fixture' });
  expect(await screen.findByTestId('compact-conversation')).toHaveTextContent('conv_existing');
  expect(mocks.resolve).toHaveBeenCalledExactlyOnceWith({ agent_id: 'agent_fixture', scope: 'agent_direct' });
  await view.rerender({ agentId: 'agent_fixture' });
  expect(mocks.resolve).toHaveBeenCalledTimes(1);
  expect(conversationWorkspace.snapshot()).toEqual(before);
  expect(mocks.send).toHaveBeenCalledWith('panel-state', { agentId: 'agent_fixture', conversationId: 'conv_existing' });
});
it.each([{ disabled: true }, { is_system: true }])('does not resolve unavailable agents: %s', async (flags) => {
  mocks.detail.mockResolvedValue({ agent_id: 'agent_fixture', ...flags });
  render(NativeDirectConversation, { agentId: 'agent_fixture' });
  await vi.waitFor(() => expect(mocks.detail).toHaveBeenCalled());
  expect(mocks.resolve).not.toHaveBeenCalled();
});
it('does not mount a late previous-account conversation after sign-out', async () => {
  let finish!: (value: unknown) => void;
  mocks.resolve.mockImplementation(() => new Promise((done) => { finish = done; }));
  render(NativeDirectConversation, { agentId: 'agent_fixture' });
  await vi.waitFor(() => expect(mocks.resolve).toHaveBeenCalled());
  state.set({ status: 'anonymous', initialized: true, user: null, expiresAt: null, error: null });
  await Promise.resolve();
  finish({ conversation_id: 'conv_old' });
  await Promise.resolve();
  expect(screen.queryByTestId('compact-conversation')).not.toBeInTheDocument();
});
