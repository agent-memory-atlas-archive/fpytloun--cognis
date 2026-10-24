import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';
import type { AuthState } from '$lib/stores/auth';
import type { CognisWebSocketEvent, Conversation } from '$lib/types/api';
import { normalizeNotification, notificationText } from '$lib/notification-events';

const mocks = vi.hoisted(() => ({ detail: vi.fn(), me: vi.fn(), task: vi.fn(), send: vi.fn(), action: vi.fn(), resolve: vi.fn(), toast: vi.fn(), observed: false,
  event: null as null | ((event: CognisWebSocketEvent) => void) }));
const state = writable<AuthState>({ status: 'anonymous', initialized: true, user: null, expiresAt: null, error: null });
const inboxState = writable({ items: [] as any[], initialized: false, loading: false, error: null });
vi.mock('$lib/stores/auth', () => ({ auth: { subscribe: (...args: Parameters<typeof state.subscribe>) => state.subscribe(...args) } }));
vi.mock('$lib/stores/inbox', () => ({ inbox: { subscribe: (...args: Parameters<typeof inboxState.subscribe>) => inboxState.subscribe(...args) } }));
vi.mock('$lib/ws/client', () => ({ wsClient: { subscribe: (event: typeof mocks.event) => {
  mocks.event = event; return () => { mocks.event = null; };
} } }));
vi.mock('$lib/api/client', () => ({ api: { conversations: { detail: mocks.detail }, auth: { me: mocks.me }, tasks: { detail: mocks.task },
  attentionActions: { get: mocks.action, resolve: mocks.resolve } } }));
vi.mock('$lib/stores/toasts', () => ({ addToast: mocks.toast }));
vi.mock('./host', () => ({ postNative: mocks.send, hostAllowsObservation: () => mocks.observed }));
import { installResidentNotifications } from './notifications';
let stop: (() => void) | undefined;
const user = (email = 'mac-companion@cognis.test') => state.set({
  status: 'authenticated', initialized: true, user: { email } as AuthState['user'], expiresAt: null, error: null,
});
const row = (overrides: Partial<Conversation> = {}): Conversation => ({
  conversation_id: 'conv_native', context: { type: 'web' }, has_unread: true,
  has_active_turn: false, last_message_at: '2026-10-15T18:43:56Z', ...overrides,
} as Conversation);
const event = (conversation = row()): CognisWebSocketEvent => ({
  type: 'sidebar_conversation_upsert', conversation_id: conversation.conversation_id, conversation,
});
const settle = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };
beforeEach(() => {
  vi.clearAllMocks(); mocks.observed = false; window.history.replaceState(null, '', '/companion');
  mocks.detail.mockResolvedValue(row()); mocks.me.mockResolvedValue({ email: 'mac-companion@cognis.test' });
  state.set({ status: 'anonymous', initialized: true, user: null, expiresAt: null, error: null });
  inboxState.set({ items: [], initialized: false, loading: false, error: null });
});
afterEach(() => { stop?.(); stop = undefined; });

describe('resident notification lifetime', () => {
  it('delivers owner-wide rows without a chat mount; dedups replay and ignores partial activity', async () => {
    user();
    const owner = installResidentNotifications(vi.fn()); stop = owner.stop;
    mocks.send.mockClear();
    mocks.event?.(event(row({ has_active_turn: true })));
    mocks.event?.(event()); mocks.event?.(event());
    await settle();
    expect(mocks.send).toHaveBeenCalledExactlyOnceWith('notification', expect.objectContaining({
      id: 'terminal:conv_native:2026-10-15T18:43:56Z', kind: 'chat', target: 'conv_native',
    }));
    expect(mocks.detail).toHaveBeenCalledTimes(1);
    stop(); expect(mocks.event).toBeNull();
  });
  it('fences late summary completion on logout, new account and teardown', async () => {
    user(); let resolve!: (value: Conversation) => void;
    mocks.detail.mockImplementation(() => new Promise<Conversation>((done) => { resolve = done; }));
    const owner = installResidentNotifications(vi.fn()); stop = owner.stop;
    mocks.event?.(event()); user('another@cognis.test'); mocks.send.mockClear();
    resolve(row()); await settle();
    expect(mocks.send).not.toHaveBeenCalledWith('notification', expect.anything());
  });
  it('suppresses observed main and canonical popup but not a closed resident surface', async () => {
    user(); const owner = installResidentNotifications(vi.fn()); stop = owner.stop;
    for (const path of ['/chat/conv_native', '/native-pinned?agent=agent_native&conversation=conv_native']) {
      window.history.replaceState(null, '', path); mocks.observed = true;
      mocks.event?.(event(row({ last_message_at: path.includes('?') ? '2026-10-15T18:44:00Z' : '2026-10-15T18:44:01Z' })));
      await settle();
    }
    expect(mocks.send).not.toHaveBeenCalledWith('notification', expect.anything());
    mocks.observed = false; mocks.event?.(event()); await settle();
    expect(mocks.send).toHaveBeenCalledWith('notification', expect.anything());
  });
  it('never alerts for managed child terminal messages or read summaries', async () => {
    user(); const owner = installResidentNotifications(vi.fn()); stop = owner.stop;
    mocks.event?.(event(row({ context: { type: 'agent_work', ref: null, platform_data: {}, memory_labels: {} } })));
    mocks.event?.(event(row({ has_unread: false }))); await settle();
    expect(mocks.send).not.toHaveBeenCalledWith('notification', expect.anything());
  });
  it('baselines canonical inbox and requires fresh identity and authorization before Review', async () => {
    user(); const navigate = vi.fn().mockResolvedValue(undefined);
    const owner = installResidentNotifications(navigate); stop = owner.stop;
    const item = { notification_id: 'inbox_native', href: '/chat/conv_native', read_at: null };
    inboxState.set({ items: [item], initialized: true, loading: false, error: null });
    await settle(); expect(mocks.send).not.toHaveBeenCalledWith('notification', expect.anything());
    owner.review({ account: 'mac-companion@cognis.test', kind: 'chat', target: 'conv_native' });
    await settle();
    expect(mocks.me).toHaveBeenCalledOnce();
    expect(navigate).toHaveBeenCalledWith('/chat/conv_native');
    navigate.mockClear(); mocks.me.mockResolvedValue({ email: 'another@cognis.test' });
    owner.review({ account: 'mac-companion@cognis.test', kind: 'chat', target: 'conv_native' });
    await settle(); expect(navigate).not.toHaveBeenCalled();
    owner.review({ account: 'mac-companion@cognis.test', kind: 'chat', target: 'https://untrusted.invalid' });
    await settle(); expect(navigate).not.toHaveBeenCalled();
  });
  it('uses bounded plain presentation and rejects nonfinal raw messages', () => {
    expect(normalizeNotification({ type: 'message_complete', conversation_id: 'conv_native',
      message_id: 'msg_native', partial: true } as CognisWebSocketEvent)).toBeNull();
    expect(notificationText('**Ready** [result](https://external.invalid)')).toBe('Ready result');
    expect(notificationText('Ready.\npassword: do-not-display')).toBe('');
    expect(notificationText('Password:\nshort-fixture\nCompleted.')).toBe('');
    expect(notificationText('Recovery codes:\n123-456\n789-012')).toBe('');
    expect(notificationText('x '.repeat(1000))).toHaveLength(240);
    expect(normalizeNotification(event(row()))?.body).toBe('');
  });
  it('captures exact completion preview, never a later async latest reply', async () => {
    user();
    let finish!: (value: Conversation) => void;
    mocks.detail.mockImplementation(() => new Promise((done) => { finish = done; }));
    const owner = installResidentNotifications(vi.fn()); stop = owner.stop;
    mocks.event?.({ ...event(), completed_reply: { message_id: 'msg_first', preview: 'First reply.' } } as CognisWebSocketEvent);
    finish(row({ title: 'Later title', agent_id: 'agent_native', agent_display_name: 'Synthetic agent' }));
    await settle();
    expect(mocks.send).toHaveBeenCalledWith('notification', expect.objectContaining({
      id: 'terminal:conv_native:msg_first',
      presentation: expect.objectContaining({ title: 'Synthetic agent', body: 'First reply.' }),
    }));
    const count = mocks.send.mock.calls.filter(([kind]) => kind === 'notification').length;
    mocks.event?.({ ...event(), completed_reply: null } as CognisWebSocketEvent);
    await settle();
    expect(mocks.send.mock.calls.filter(([kind]) => kind === 'notification')).toHaveLength(count);
  });

  const approval = (overrides: Record<string, unknown> = {}) => ({
    action_id: 'attention_native', kind: 'escalation', status: 'pending', availability: 'actionable',
    can_resolve: true, has_action_form: true, revision: 3, expires_at: null,
    display: { tool_name: 'fixture_read', questions: [], required_fields: [] },
    allowed_actions: [{ action: 'approve', label: 'Approve', input: 'note' }, { action: 'deny', label: 'Deny', input: 'note' }],
    ...overrides,
  });
  async function offered() {
    mocks.action.mockResolvedValue(approval());
    mocks.event?.(event(row({ attention_actions: [{
      action_id: 'attention_native', status: 'pending', title: 'Tool approval',
      source: { notification_id: 'inbox_approval', conversation_id: 'conv_native' },
    }] as Conversation['attention_actions'] })));
    await vi.waitFor(() => expect(mocks.send.mock.calls.some(
      ([kind, value]) => kind === 'notification' && value.presentation.approval)).toBe(true));
    const payload = mocks.send.mock.calls.find(([kind, value]) => kind === 'notification' && value.presentation.approval)?.[1];
    expect(payload).toBeTruthy();
    return { ...payload.presentation.approval, account: 'mac-companion@cognis.test', scope: payload.scope, decision: 'approve' };
  }
  it('uses the live canonical API once and reports success only after acknowledgment', async () => {
    user(); const owner = installResidentNotifications(vi.fn()); stop = owner.stop;
    const command = await offered();
    let acknowledge!: (value: unknown) => void;
    mocks.resolve.mockImplementation(() => new Promise((done) => { acknowledge = done; }));
    const pending = owner.act(command);
    await vi.waitFor(() => expect(mocks.resolve).toHaveBeenCalled());
    expect(mocks.resolve).toHaveBeenCalledExactlyOnceWith('attention_native', {
      action: 'approve', expected_revision: 3, submission_id: command.submissionId,
    });
    expect(mocks.toast).not.toHaveBeenCalledWith(expect.anything(), 'success');
    await owner.act(command);
    expect(mocks.resolve).toHaveBeenCalledTimes(1);
    acknowledge({ status: 'resolved' }); await pending;
    expect(mocks.toast).toHaveBeenCalledWith('Tool request approved.', 'success');
  });
  it.each(['revision', 'expired', 'credential', 'account', 'offline', 'scope', 'submission', 'changed', 'signed-out'])(
    'sends %s approvals to Review, never executes or replays after sign-in', async (invalid) => {
      user(); const navigate = vi.fn(); const owner = installResidentNotifications(navigate); stop = owner.stop;
      const command = await offered();
      if (invalid === 'revision') mocks.action.mockResolvedValue(approval({ revision: 4 }));
      if (invalid === 'expired') mocks.action.mockResolvedValue(approval({ expires_at: '2020-01-01T00:00:00Z' }));
      if (invalid === 'credential') mocks.action.mockResolvedValue(approval({ kind: 'credential_request' }));
      if (invalid === 'changed') mocks.action.mockResolvedValue(approval({ can_resolve: false }));
      if (invalid === 'account') user('another@cognis.test');
      if (invalid === 'offline') state.update((s) => ({ ...s, offline: true }));
      if (invalid === 'scope') command.scope = crypto.randomUUID();
      if (invalid === 'submission') command.submissionId = crypto.randomUUID();
      if (invalid === 'signed-out') state.update((s) => ({ ...s, status: 'anonymous', user: null }));
      await owner.act(command);
      expect(mocks.resolve).not.toHaveBeenCalled();
      expect(navigate).toHaveBeenCalled();
      user(); await settle();
      expect(mocks.resolve).not.toHaveBeenCalled();
    });
});
