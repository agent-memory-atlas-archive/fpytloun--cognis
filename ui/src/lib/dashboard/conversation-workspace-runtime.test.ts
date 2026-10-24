import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get, writable } from 'svelte/store';
import type { Conversation } from '$lib/types/api';

const mocks = vi.hoisted(() => ({
  detail: vi.fn(), agents: vi.fn(), sidebar: vi.fn(), background: vi.fn(),
  listener: null as null | ((event: Record<string, unknown>) => void),
}));
vi.mock('$lib/api/client', () => ({
  api: { conversations: { detail: mocks.detail, sidebar: mocks.sidebar, backgroundWork: mocks.background }, agents: { listAll: mocks.agents } },
  asApiError: (error: unknown) => error,
}));
vi.mock('$lib/stores/auth', () => ({
  auth: writable({ status: 'anonymous', user: null as null | { email: string } }),
}));
vi.mock('$lib/ws/client', () => ({
  wsClient: { subscribe: (callback: typeof mocks.listener) => {
    mocks.listener = callback; return () => { mocks.listener = null; };
  } },
  wsState: writable({ status: 'idle' }),
}));
import { auth } from '$lib/stores/auth';
import { wsState } from '$lib/ws/client';
import { conversationWorkspace } from './conversation-workspace';
import { startConversationWorkspace, pinnedConversations, pinnedBackgroundWork, pinnedActivityAt } from './conversation-workspace-runtime';

const conversation = {
  conversation_id: 'chat-one', agent_id: 'agent-one', title: 'Chat one', project_id: null,
  status: 'active', context: { type: 'web' }, has_unread: true, has_active_turn: false,
  last_message_at: '2026-10-14T08:00:00Z', pending_notification_types: [],
} as unknown as Conversation;
function signIn(email: string) {
  (auth as unknown as ReturnType<typeof writable>).set({ status: 'authenticated', user: { email } });
}
async function flush() { for (let index = 0; index < 5; index++) await Promise.resolve(); }
let stop: () => void;
beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  (auth as unknown as ReturnType<typeof writable>).set({ status: 'anonymous', user: null });
  mocks.detail.mockReset().mockResolvedValue(conversation);
  mocks.agents.mockReset().mockResolvedValue([]);
  mocks.sidebar.mockReset();
  mocks.background.mockReset().mockResolvedValue({ background_work: { items: [] }, background_work_changed: true });
  stop = startConversationWorkspace();
  signIn('owner@cognis.test');
});
afterEach(() => { stop(); vi.useRealTimers(); });

describe('retained conversation summaries', () => {
  it('records real activity, not opening/read metadata, and clears it with pin/account ownership', async () => {
    await conversationWorkspace.pin(conversation);
    await vi.advanceTimersByTimeAsync(100);
    expect(get(pinnedActivityAt)).toEqual({});
    mocks.detail.mockResolvedValue({ ...conversation, updated_at: '2099-01-01T00:00:00Z',
      active_session_updated_at: '2099-01-01T00:00:00Z', has_unread: false });
    mocks.listener?.({ type: 'conversation_updated', conversation_id: 'chat-one', has_unread: false });
    await vi.advanceTimersByTimeAsync(100);
    expect(get(pinnedActivityAt)).toEqual({});
    mocks.listener?.({ type: 'turn_started', conversation_id: 'chat-one' });
    const started = get(pinnedActivityAt)['chat-one'];
    expect(started).toBeGreaterThan(0);
    await vi.advanceTimersByTimeAsync(100);
    mocks.listener?.({ type: 'message_complete', conversation_id: 'chat-one' });
    expect(get(pinnedActivityAt)['chat-one']).toBeGreaterThan(started);
    await vi.advanceTimersByTimeAsync(100);
    mocks.listener?.({ type: 'conversation_updated', conversation_id: 'chat-one', pending_notification_types: ['step_question'] });
    const notified = get(pinnedActivityAt)['chat-one'];
    await vi.advanceTimersByTimeAsync(100);
    mocks.listener?.({ type: 'conversation_updated', conversation_id: 'chat-one', pending_notification_types: [] });
    expect(get(pinnedActivityAt)['chat-one']).toBe(notified);
    mocks.listener?.({ type: 'turn_started', conversation_id: 'unretained-chat' });
    expect(get(pinnedActivityAt)['unretained-chat']).toBeUndefined();
    await conversationWorkspace.unpin('conversation:chat-one');
    expect(get(pinnedActivityAt)).toEqual({});
    await conversationWorkspace.pin(conversation);
    mocks.listener?.({ type: 'turn_started', conversation_id: 'chat-one' });
    signIn('other@cognis.test');
    expect(get(pinnedActivityAt)).toEqual({});
  });

  it('batches collapsed-pin realtime refreshes and never loads a timeline', async () => {
    expect(mocks.agents).not.toHaveBeenCalled();
    await conversationWorkspace.pin(conversation);
    for (let index = 0; index < 20; index++) mocks.listener?.({ type: 'turn_started', conversation_id: 'chat-one' });
    await vi.advanceTimersByTimeAsync(100);
    expect(mocks.detail).toHaveBeenCalledTimes(1);
    expect(mocks.detail).toHaveBeenCalledWith('chat-one', { includeState: false });
    expect(get(pinnedConversations)['chat-one'].has_unread).toBe(true);
    expect(mocks.background).toHaveBeenCalledTimes(1);
    expect(mocks.sidebar).not.toHaveBeenCalled();
  });

  it('preserves realtime fields newer than an in-flight summary without freezing other fields', async () => {
    await conversationWorkspace.pin(conversation);
    await vi.advanceTimersByTimeAsync(100);
    let resolve!: (value: Conversation) => void;
    mocks.detail.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    mocks.listener?.({ type: 'turn_started', conversation_id: 'chat-one' });
    await vi.advanceTimersByTimeAsync(100);
    mocks.listener?.({ type: 'sidebar_conversation_upsert', conversation_id: 'chat-one', has_active_turn: true });
    resolve({ ...conversation, title: 'Fresh title', has_active_turn: false });
    await flush();
    expect(get(pinnedConversations)['chat-one'].has_active_turn).toBe(true);
    expect(get(pinnedConversations)['chat-one'].title).toBe('Fresh title');
  });

  it('does not publish an unpinned or previous-account request', async () => {
    let resolve!: (value: Conversation) => void;
    mocks.detail.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    await conversationWorkspace.pin(conversation);
    await vi.advanceTimersByTimeAsync(100);
    await conversationWorkspace.unpin('conversation:chat-one');
    resolve(conversation);
    await flush();
    expect(get(pinnedConversations)).toEqual({});
    mocks.detail.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    await conversationWorkspace.pin(conversation);
    await vi.advanceTimersByTimeAsync(100);
    signIn('other@cognis.test');
    resolve(conversation);
    await flush();
    expect(get(pinnedConversations)).toEqual({});
    expect(conversationWorkspace.snapshot().entries).toEqual([]);
  });

  it('refreshes unread and background status after reconnect', async () => {
    await conversationWorkspace.pin(conversation);
    await vi.advanceTimersByTimeAsync(100);
    mocks.detail.mockResolvedValue({ ...conversation, has_unread: false, pending_notification_types: ['step_question'] });
    mocks.background.mockResolvedValue({ background_work: { items: [{ controller_conversation_id: 'chat-one', status: 'running' }] }, background_work_changed: true });
    wsState.set({ status: 'connected' } as never);
    await vi.advanceTimersByTimeAsync(100);
    expect(get(pinnedConversations)['chat-one'].pending_notification_types).toEqual(['step_question']);
    expect(get(pinnedBackgroundWork)).toHaveLength(1);
  });

  it('removes inaccessible chats but retains pins on transient failures', async () => {
    await conversationWorkspace.pin(conversation);
    mocks.detail.mockRejectedValue({ status: 503 });
    await vi.advanceTimersByTimeAsync(100);
    expect(conversationWorkspace.snapshot().entries).toHaveLength(1);
    mocks.detail.mockRejectedValue({ status: 403 });
    mocks.listener?.({ type: 'turn_settled', conversation_id: 'chat-one' });
    await vi.advanceTimersByTimeAsync(100);
    expect(conversationWorkspace.snapshot().entries).toEqual([]);
  });

  it('serializes background-only bursts and preserves complete data during partial failures', async () => {
    let resolve!: (value: unknown) => void;
    mocks.background.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    await conversationWorkspace.pin(conversation);
    await vi.advanceTimersByTimeAsync(100);
    for (let index = 0; index < 20; index++) {
      mocks.listener?.({ type: 'work_invalidated' });
      await vi.advanceTimersByTimeAsync(100);
    }
    expect(mocks.background).toHaveBeenCalledTimes(1);
    const work = [{ controller_conversation_id: 'chat-one', status: 'running' }];
    resolve({ background_work: { items: work }, background_work_changed: true });
    await flush();
    mocks.background.mockResolvedValue({ background_work: { items: [] }, background_work_changed: false });
    await vi.advanceTimersByTimeAsync(4_100);
    expect(mocks.background).toHaveBeenCalledTimes(2);
    expect(get(pinnedBackgroundWork)).toEqual(work);
    expect(mocks.sidebar).not.toHaveBeenCalled();
  });

  it('resets a background authorization block on same-account reauthentication', async () => {
    mocks.background.mockRejectedValueOnce(Object.assign(new Error('expired'), { status: 401 }));
    await conversationWorkspace.pin(conversation);
    await vi.advanceTimersByTimeAsync(100);
    expect(mocks.background).toHaveBeenCalledTimes(1);
    mocks.listener?.({ type: 'work_invalidated' });
    await vi.advanceTimersByTimeAsync(5_000);
    expect(mocks.background).toHaveBeenCalledTimes(1);
    const work = [{ controller_conversation_id: 'chat-one', status: 'running' }];
    mocks.background.mockResolvedValue({ background_work: { items: work }, background_work_changed: true });
    (auth as unknown as ReturnType<typeof writable>).set({ status: 'anonymous', user: null });
    signIn('owner@cognis.test');
    await conversationWorkspace.pin(conversation);
    (wsState as unknown as ReturnType<typeof writable>).set({ status: 'connected' });
    await vi.advanceTimersByTimeAsync(100);
    expect(mocks.background).toHaveBeenCalledTimes(2);
    expect(get(pinnedBackgroundWork)).toEqual(work);
  });
});
