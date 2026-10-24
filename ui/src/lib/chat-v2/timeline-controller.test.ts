import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { emptyChatV2State } from './sync-engine';
import { conversationTimelineScope, type ChatRealtimeFrame, type ChatSnapshot, type ChatSyncResponse, type TimelineBackfillResponse } from './types';

const device = vi.hoisted(() => ({
  owner: 'timeline-fixture@cognis.test' as string | null,
  rows: new Map<string, unknown>(),
  ownerChanged: () => {},
}));
vi.mock('$lib/offline/cache', () => ({
  offlineCache: {
    get currentOwner() { return device.owner; },
    onOwnerChange: (listener: () => void) => { device.ownerChanged = listener; },
    get: async (kind: string, id: string) => device.rows.get(`${kind}:${id}`) ?? null,
    put: vi.fn(async (kind: string, id: string, value: unknown) => {
      device.rows.set(`${kind}:${id}`, value); return true;
    }),
  },
}));
import { acquireTimeline, clearTimelineMemory, timelineResourceCounts, TimelineProviderConflictError } from './timeline-controller.svelte';
import { offlineCache } from '$lib/offline/cache';

const scope = conversationTimelineScope('timeline-fixture');
function snapshot(): ChatSnapshot {
  return {
    schema_version: 2, projection_version: 'test', scope,
    conversation: { conversation_id: scope.conversation_id!, agent_id: 'fixture', status: 'active' },
    cursor: 'cursor:initial', server_time: '',
    timeline: { items: [], has_more_before: false, before_cursor: null },
    state: { state_version: 1, active_turn: {}, pending: {}, active_session: {}, capabilities: [] },
    queue: { messages: [], queued_count: 0 },
    runtime: null,
  } as unknown as ChatSnapshot;
}
function delta(cursor = 'cursor:initial'): ChatSyncResponse {
  return {
    schema_version: 2, projection_version: 'test', conversation_id: scope.conversation_id,
    scope, cursor_before: cursor, cursor_after: cursor, has_more: false,
    ops: [], runtime: null, reset_required: false, server_time: '',
  } as ChatSyncResponse;
}
function api() {
  return {
    snapshot: vi.fn(async () => snapshot()),
    sync: vi.fn(async (_scope: unknown, cursor: string) => delta(cursor)),
    timeline: vi.fn(),
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe('canonical timeline ownership', () => {
  it('isolates a provider conflict until all original consumers release', async () => {
    const original = api();
    const replacement = api();
    const first = acquireTimeline(scope, original);
    const sibling = acquireTimeline(scope, original);
    await first.controller.load();
    first.release();
    expect(() => acquireTimeline(scope, replacement)).toThrow(TimelineProviderConflictError);
    expect(sibling.controller.current).toBe(true);
    await sibling.controller.load();
    expect(original.sync).toHaveBeenCalledOnce();
    expect(replacement.snapshot).not.toHaveBeenCalled();
    sibling.release();
    const next = acquireTimeline(scope, replacement);
    await next.controller.load();
    expect(next.controller).not.toBe(sibling.controller);
    expect(replacement.snapshot.mock.calls.length + replacement.sync.mock.calls.length).toBeGreaterThan(0);
    next.release();
  });

  it('fences a late old-provider completion after its last consumer releases', async () => {
    const original = api();
    const held = deferred<ChatSnapshot>();
    original.snapshot.mockReturnValue(held.promise);
    const first = acquireTimeline(scope, original);
    const flight = first.controller.load().catch(error => error);
    await vi.waitFor(() => expect(original.snapshot).toHaveBeenCalledOnce());
    first.release();
    const replacement = api();
    const next = acquireTimeline(scope, replacement);
    await next.controller.load();
    held.resolve({ ...snapshot(), cursor: 'cursor:obsolete-provider' });
    await flight;
    expect(first.controller.current).toBe(false);
    expect(next.controller.store.snapshot.cursor).toBe('cursor:initial');
    next.release();
  });

  it('uses the replacement API when an account-owned scope is reacquired', async () => {
    const original = api();
    const replacement = api();
    const first = acquireTimeline(scope, original);
    await first.controller.load();
    first.release();
    const second = acquireTimeline(scope, replacement);
    try {
      await second.controller.load();
      expect(replacement.snapshot.mock.calls.length + replacement.sync.mock.calls.length).toBeGreaterThan(0);
      expect(original.sync).not.toHaveBeenCalled();
    } finally {
      second.release();
    }
  });
  afterEach(() => { clearTimelineMemory(); vi.restoreAllMocks(); });
  beforeEach(() => {
    clearTimelineMemory();
    device.owner = 'timeline-fixture@cognis.test';
    device.rows.clear();
  });

  it('full chat -> compact -> full chat retains one store and never downloads another snapshot', async () => {
    const client = api();
    const full = acquireTimeline(scope, client);
    await full.controller.load();
    full.release();
    const embedded = acquireTimeline(scope, client);
    expect(embedded.controller.store).toBe(full.controller.store);
    await embedded.controller.load();
    embedded.release();
    const fullAgain = acquireTimeline(scope, client);
    await fullAgain.controller.load();
    expect(fullAgain.controller.store).toBe(full.controller.store);
    expect(client.snapshot).toHaveBeenCalledTimes(1);
    expect(client.sync).toHaveBeenCalledTimes(2);
    expect(timelineResourceCounts()).toEqual({ entries: 1, retained: 1 });
    fullAgain.release();
  });

  it('drains an invalidation received during a held snapshot through cursor sync', async () => {
    const client = api();
    const pending = deferred<ChatSnapshot>();
    client.snapshot.mockReturnValue(pending.promise);
    const view = acquireTimeline(scope, client);
    const loading = view.controller.load();
    await vi.waitFor(() => expect(client.snapshot).toHaveBeenCalledOnce());
    expect(view.controller.admitInvalidation({
      type: 'scope_invalidated', reason: 'chat_scope_changed',
      conversation_id: scope.conversation_id!, scope_key: scope.key, revision: 'admission-2',
    })).toBe(true);
    pending.resolve(snapshot());
    await loading;
    expect(client.snapshot).toHaveBeenCalledOnce();
    expect(client.sync).toHaveBeenCalledOnce();
    expect(client.sync.mock.calls[0][1]).toBe('cursor:initial');
    view.release();
  });

  it('shares repeated admitted hints with upstream freshness and drains a forced snapshot via sync', async () => {
    const client = api();
    const pending = deferred<ChatSnapshot>();
    const trailing = deferred<ChatSyncResponse>();
    client.snapshot.mockReturnValueOnce(pending.promise);
    client.sync.mockReturnValueOnce(trailing.promise);
    const view = acquireTimeline(scope, client);
    const loading = view.controller.load({ forceSnapshot: true });
    await vi.waitFor(() => expect(client.snapshot).toHaveBeenCalledOnce());
    for (let revision = 0; revision < 100; revision++) {
      expect(view.controller.admitInvalidation({
        type: 'scope_invalidated', reason: 'chat_scope_changed',
        scope_key: scope.key, revision: String(revision),
      })).toBe(true);
    }
    pending.resolve(snapshot());
    await vi.waitFor(() => expect(client.sync).toHaveBeenCalledOnce());
    expect(view.controller.reconciled).toBe(false);
    expect(client.snapshot).toHaveBeenCalledOnce();
    trailing.resolve(delta());
    await loading;
    expect(view.controller.reconciled).toBe(true);
    view.release();
  });

  it.each([
    ['executor_state_changed', {}, false],
    ['schedule_action_changed', { conversation_id: scope.conversation_id! }, false],
    ['chat_scope_changed', {}, true],
    ['chat_scope_changed', { scope_key: scope.key }, true],
    ['event_store_session_invalidated', {}, true],
    ['event_store_session_invalidated', { session_id: 'foreign-session' }, false],
  ] as const)('admits %s %j through the in-flight epoch exactly once', async (reason, routing, accepted) => {
    const client = api();
    const pending = deferred<ChatSnapshot>();
    client.snapshot.mockReturnValue(pending.promise);
    const view = acquireTimeline(scope, client);
    try {
      const loading = view.controller.load();
      await vi.waitFor(() => expect(client.snapshot).toHaveBeenCalledOnce());
      expect(view.controller.admitInvalidation({
        type: 'scope_invalidated', revision: 'integration-parity', reason, ...routing,
      })).toBe(accepted);
      pending.resolve(snapshot());
      await loading;
      expect(client.snapshot).toHaveBeenCalledOnce();
      expect(client.sync).toHaveBeenCalledTimes(accepted ? 1 : 0);
      if (accepted) expect(client.sync.mock.calls[0][1]).toBe('cursor:initial');
    } finally {
      view.release();
    }
  });

  it('independent registries recover a post-append hint after an early admission read saw no change', async () => {
    const originalOwnerChanged = device.ownerChanged;
    vi.resetModules();
    const senderRegistry = await import('./timeline-controller.svelte');
    vi.resetModules();
    const recipientRegistry = await import('./timeline-controller.svelte');
    const senderApi = api();
    const recipientApi = api();
    const sender = senderRegistry.acquireTimeline(scope, senderApi);
    const recipient = recipientRegistry.acquireTimeline(scope, recipientApi);
    try {
      await Promise.all([sender.controller.load(), recipient.controller.load()]);
      expect(sender.controller).not.toBe(recipient.controller);
      expect(sender.controller.store).not.toBe(recipient.controller.store);
      const early = {
        type: 'scope_invalidated' as const, reason: 'chat_scope_changed' as const,
        scope_key: scope.key, conversation_id: scope.conversation_id!, revision: 'early-admission',
      };
      for (const view of [sender, recipient]) {
        expect(view.controller.admitInvalidation(early)).toBe(true);
        await view.controller.load();
        expect(view.controller.store.snapshot.cursor).toBe('cursor:initial');
      }
      // Both clients already consumed the early hint. Only the post-append
      // event can expose these two equal-text, distinct-identity messages.
      const committed = delta();
      committed.cursor_after = 'cursor:committed';
      committed.ops = ['first-admission', 'second-admission'].map(id => ({
        op: 'upsert_item' as const,
        item: {
          id: `user:${id}`, kind: 'message' as const, role: 'user' as const,
          message_id: id, client_message_id: id, content: 'Repeated synthetic text',
          sort_key: id, status: 'complete', stable: true, partial: false, attachments: [],
          source_refs: [{ store: 'intaris' as const, session_id: 'session-fixture', seq: id === 'first-admission' ? 1 : 2, event_type: 'user_message' }],
        },
      }));
      senderApi.sync.mockResolvedValue(committed);
      recipientApi.sync.mockResolvedValue(committed);
      const appended = {
        type: 'scope_invalidated' as const, reason: 'event_store_session_invalidated' as const,
        revision: 'durable-append',
      };
      for (const view of [sender, recipient]) {
        expect(view.controller.admitInvalidation(appended)).toBe(true);
        await view.controller.load();
        expect(view.controller.store.snapshot.cursor).toBe('cursor:committed');
      }
      // Replay must not duplicate content; no local optimism or sender ACK
      // has populated either store.
      for (const view of [sender, recipient]) {
        view.controller.admitInvalidation(appended);
        await view.controller.load();
        const messages = view.controller.store.snapshot.timelineItems.filter(item => item.kind === 'message');
        expect(messages.map(item => item.id).sort()).toEqual(['user:first-admission', 'user:second-admission']);
        expect(messages.map(item => item.content)).toEqual(['Repeated synthetic text', 'Repeated synthetic text']);
      }
      expect(senderApi.snapshot).toHaveBeenCalledOnce();
      expect(recipientApi.snapshot).toHaveBeenCalledOnce();
    } finally {
      sender.release();
      recipient.release();
      senderRegistry.clearTimelineMemory();
      recipientRegistry.clearTimelineMemory();
      device.ownerChanged = originalOwnerChanged;
    }
  });

  it('coalesces same-scope opens; closing one consumer leaves the other request alive', async () => {
    const pending = deferred<ChatSnapshot>();
    const client = api();
    client.snapshot.mockReturnValue(pending.promise);
    const first = acquireTimeline(scope, client);
    const second = acquireTimeline(scope, client);
    const close = new AbortController();
    const a = first.controller.load({ signal: close.signal });
    const b = second.controller.load();
    const aborted = expect(a).rejects.toMatchObject({ name: 'AbortError' });
    await vi.waitFor(() => expect(client.snapshot).toHaveBeenCalledTimes(1));
    close.abort();
    first.release();
    await aborted;
    expect((client.snapshot.mock.calls[0] as unknown as [unknown, { signal: AbortSignal }])[1].signal.aborted).toBe(false);
    pending.resolve(snapshot());
    await b;
    expect(second.controller.store.snapshot.cursor).toBe('cursor:initial');
    second.release();
  });

  it('keeps one trailing invalidation while equivalent opens share the held sync', async () => {
    const client = api();
    const view = acquireTimeline(scope, client);
    await view.controller.load();
    expect(view.controller.reconciled).toBe(true);
    const held = deferred<ChatSyncResponse>();
    client.sync.mockReturnValueOnce(held.promise);
    client.sync.mockResolvedValueOnce({
      ...delta(), cursor_after: 'cursor:newer',
    });
    const initial = view.controller.load();
    await vi.waitFor(() => expect(client.sync).toHaveBeenCalledTimes(1));
    const equivalent = view.controller.load();
    const invalidations = Array.from({ length: 100 }, () =>
      view.controller.load({ invalidate: true }));
    expect(view.controller.reconciled).toBe(false);
    expect(client.sync).toHaveBeenCalledTimes(1);
    held.resolve(delta());
    await Promise.all([initial, equivalent, ...invalidations]);
    expect(client.sync).toHaveBeenCalledTimes(2);
    expect(view.controller.store.snapshot.cursor).toBe('cursor:newer');
    expect(view.controller.reconciled).toBe(true);
    view.release();
  });

  it('does not execute a dirty trailing refresh after account revocation', async () => {
    const client = api();
    const view = acquireTimeline(scope, client);
    await view.controller.load();
    const held = deferred<ChatSyncResponse>();
    client.sync.mockReturnValueOnce(held.promise);
    const initial = view.controller.load();
    await vi.waitFor(() => expect(client.sync).toHaveBeenCalledTimes(1));
    const trailing = view.controller.load({ invalidate: true });
    const rejected = Promise.all([
      expect(initial).rejects.toMatchObject({ code: 'timeline_owner_changed' }),
      expect(trailing).rejects.toMatchObject({ code: 'timeline_owner_changed' }),
    ]);
    device.owner = 'other-fixture@cognis.test';
    device.ownerChanged();
    held.resolve(delta());
    await rejected;
    expect(client.sync).toHaveBeenCalledTimes(1);
    expect(view.controller.reconciled).toBe(false);
  });

  it('reports cached history as unreconciled until the server responds', async () => {
    const state = { ...emptyChatV2State(), scopeKey: scope.key, conversationId: scope.conversation_id!, cursor: 'cached' };
    device.rows.set(`timeline:${scope.key}`, { state });
    const client = api();
    const held = deferred<ChatSyncResponse>();
    client.sync.mockReturnValueOnce(held.promise);
    const view = acquireTimeline(scope, client);
    await view.controller.hydrate();
    expect(view.controller.store.snapshot.cursor).toBe('cached');
    expect(view.controller.reconciled).toBe(false);
    const fresh = view.controller.load();
    held.resolve(delta('cached'));
    await fresh;
    expect(view.controller.reconciled).toBe(true);
    view.release();
  });

  it('rejects invalid ownership before any cache, network or history work can start', async () => {
    const client = api();
    const cache = vi.spyOn(offlineCache, 'get');
    const view = acquireTimeline(scope, client);
    view.controller.invalidate();
    expect(view.controller.phase).toBe('identity-required');
    await expect(view.controller.hydrate()).rejects.toMatchObject({ code: 'timeline_owner_changed' });
    expect(() => view.controller.load()).toThrow(expect.objectContaining({ code: 'timeline_owner_changed' }));
    expect(() => view.controller.older('obsolete-owner-cursor')).toThrow(expect.objectContaining({ code: 'timeline_owner_changed' }));
    expect(cache).not.toHaveBeenCalled();
    expect(client.snapshot).not.toHaveBeenCalled();
    expect(client.timeline).not.toHaveBeenCalled();
    expect(timelineResourceCounts()).toEqual({ entries: 0, retained: 0 });
  });

  it('invalidates old-owner state and rejects a late network completion', async () => {
    const client = api();
    const pending = deferred<ChatSnapshot>();
    client.snapshot.mockReturnValue(pending.promise);
    const first = acquireTimeline(scope, client);
    const loading = first.controller.load();
    const rejected = expect(loading).rejects.toMatchObject({ name: 'TimelineOwnershipError', code: 'timeline_owner_changed' });
    await vi.waitFor(() => expect(client.snapshot).toHaveBeenCalled());
    device.owner = 'other-fixture@cognis.test';
    device.ownerChanged();
    pending.resolve(snapshot());
    await rejected;
    expect(first.controller.store.snapshot.cursor).toBeNull();
    expect(device.rows.size).toBe(0);
    expect(acquireTimeline(scope, client).controller).not.toBe(first.controller);
  });

  it('a runtime mutation during snapshot wins its watermark', async () => {
    const client = api();
    const view = acquireTimeline(scope, client);
    await view.controller.load();
    const pending = deferred<ChatSnapshot>();
    client.snapshot.mockReturnValue(pending.promise);
    const loading = view.controller.load({ forceSnapshot: true });
    await vi.waitFor(() => expect(client.snapshot).toHaveBeenCalledTimes(2));
    expect(view.controller.store.applyRealtime({
      type: 'chat_v2_frame', schema_version: 2, projection_version: 'test', scope,
      conversation_id: scope.conversation_id!, cursor_before: 'cursor:initial', cursor_after: 'cursor:live',
      ops: [], server_time: '', runtime: {
        runtime_epoch: 'live', runtime_revision: 1, generated_at: '',
        has_active_turn: false, active_turn: null, volatile_items: [], cycle_states: [],
      },
    } as ChatRealtimeFrame).outcome).toBe('applied');
    pending.resolve(snapshot());
    expect(await loading).toBeNull();
    expect(view.controller.store.snapshot.cursor).toBe('cursor:live');
  });

  it('accepts the required reset base despite an intervening runtime-only frame', async () => {
    const client = api();
    const view = acquireTimeline(scope, client);
    await view.controller.load();
    client.sync.mockResolvedValue({ ...delta(), reset_required: true, reset_reason: 'cursor_expired' });
    const pending = deferred<ChatSnapshot>();
    client.snapshot.mockReturnValue(pending.promise);
    const loading = view.controller.load();
    await vi.waitFor(() => expect(client.snapshot).toHaveBeenCalledTimes(2));
    expect(view.controller.store.snapshot.syncStatus).toBe('gapped');
    const result = view.controller.store.applyRealtime({
      type: 'chat_v2_frame', schema_version: 2, projection_version: 'test', scope,
      conversation_id: scope.conversation_id!, cursor_before: 'cursor:subscription', cursor_after: 'cursor:subscription',
      ops: [], server_time: '', runtime: {
        runtime_epoch: 'live', runtime_revision: 1, generated_at: '',
        has_active_turn: false, active_turn: null, volatile_items: [], cycle_states: [],
      },
    } as ChatRealtimeFrame);
    expect(result.outcome).toBe('applied');
    pending.resolve({ ...snapshot(), cursor: 'cursor:recovered' });
    await loading;
    expect(view.controller.store.snapshot.syncStatus).toBe('ready');
    expect(view.controller.phase).toBe('ready');
    expect(view.controller.store.snapshot.cursor).toBe('cursor:recovered');
    expect(view.controller.store.snapshot.runtime?.runtime_epoch).toBe('live');
  });

  it('migrates the newest deployed device format, but writes only canonical timelines', async () => {
    const state = { ...emptyChatV2State(), scopeKey: scope.key, conversationId: scope.conversation_id!, cursor: 'new' };
    device.rows.set(`scoped-view:${scope.key}`, { state: { ...state, cursor: 'old' }, savedAt: 1 });
    device.rows.set(`conversation-view:${scope.conversation_id}`, { chatV2State: state, fetchedAt: 2 });
    const view = acquireTimeline(scope, api());
    await view.controller.hydrate();
    expect(view.controller.store.snapshot.cursor).toBe('new');
    expect(device.rows.get(`timeline:${scope.key}`)).toMatchObject({ state: { cursor: 'new' } });
  });

  it.each(['local', 'canonical', 'reset'] as const)('settles held recovery after intervening %s admission', async kind => {
    const client = api();
    const view = acquireTimeline(scope, client);
    await view.controller.load();
    client.sync.mockResolvedValue({ ...delta(), reset_required: true, reset_reason: 'cursor_expired' });
    const pending = deferred<ChatSnapshot>();
    client.snapshot.mockReturnValue(pending.promise);
    const loading = view.controller.load();
    const settled = kind === 'reset'
      ? expect(loading).rejects.toThrow('Timeline history changed during recovery. Try again.')
      : expect(loading).resolves.toEqual(kind === 'canonical' ? null : expect.anything());
    await vi.waitFor(() => expect(client.snapshot).toHaveBeenCalledTimes(2));
    if (kind === 'local') view.controller.store.addOptimisticUser({ content: 'local', clientMessageId: 'local-during-reset' });
    if (kind === 'canonical') view.controller.store.applySync({ ...delta(), cursor_after: 'cursor:new-canonical' });
    if (kind === 'reset') view.controller.store.applySync({ ...delta(), reset_required: true, reset_reason: 'lineage_changed' });
    pending.resolve({ ...snapshot(), cursor: 'cursor:recovered' });
    await settled;
    expect(client.snapshot).toHaveBeenCalledTimes(2);
    expect(view.controller.phase).toBe(kind === 'reset' ? 'error' : 'ready');
    expect(view.controller.store.snapshot.syncStatus).toBe(kind === 'reset' ? 'gapped' : 'ready');
    if (kind === 'canonical') expect(view.controller.store.snapshot.cursor).toBe('cursor:new-canonical');
    if (kind === 'local') expect(view.controller.store.visibleItems).toEqual(expect.arrayContaining([expect.objectContaining({ content: 'local' })]));
    view.release();
  });

  it('deduplicates a shared older page and preserves the other view when one closes midflight', async () => {
    const client = api();
    const first = acquireTimeline(scope, client);
    const second = acquireTimeline(scope, client);
    await first.controller.load();
    const pending = deferred<TimelineBackfillResponse>();
    client.timeline.mockReturnValue(pending.promise);
    const apply = vi.spyOn(first.controller.store, 'applyBackfill');
    const prepare = vi.fn(() => vi.fn());
    const stop = first.controller.store.observeMembership(prepare);
    const close = new AbortController();
    const a = first.controller.older('before:shared', close.signal);
    const b = second.controller.older('before:shared');
    const aborted = expect(a).rejects.toMatchObject({ name: 'AbortError' });
    stop();
    close.abort();
    first.release();
    await aborted;
    expect(client.timeline).toHaveBeenCalledOnce();
    expect(client.timeline.mock.calls[0][1].signal.aborted).toBe(false);
    pending.resolve({
      schema_version: 2, projection_version: 'test', scope, conversation_id: scope.conversation_id!,
      items: [], before_cursor: null, has_more_before: false, server_time: '',
    });
    await b;
    expect(apply).toHaveBeenCalledOnce();
    expect(prepare).not.toHaveBeenCalled();
    second.release();
  });

  it('rejects a late device hydration after logout without repopulating memory or writing a previous owner', async () => {
    const pending = deferred<{ state: ReturnType<typeof emptyChatV2State> }>();
    vi.spyOn(offlineCache, 'get').mockReturnValue(pending.promise as never);
    const view = acquireTimeline(scope, api());
    const hydration = view.controller.hydrate();
    const rejected = expect(hydration).rejects.toMatchObject({ name: 'TimelineOwnershipError', code: 'timeline_owner_changed' });
    device.owner = null;
    device.ownerChanged();
    pending.resolve({ state: {
      ...emptyChatV2State(), scopeKey: scope.key, conversationId: scope.conversation_id!, cursor: 'previous-owner',
    } });
    await rejected;
    expect(view.controller.store.snapshot.cursor).toBeNull();
    expect(timelineResourceCounts()).toEqual({ entries: 0, retained: 0 });
    expect(device.rows.size).toBe(0);
  });

  it('adopts local admissions made during a cold snapshot without blocking canonical bootstrap', async () => {
    const pending = deferred<ChatSnapshot>();
    const client = api();
    client.snapshot.mockReturnValue(pending.promise);
    const view = acquireTimeline(scope, client);
    const loading = view.controller.load();
    await vi.waitFor(() => expect(client.snapshot).toHaveBeenCalledOnce());
    view.controller.store.addOptimisticUser({
      content: 'Local admission during bootstrap', attachments: [],
      clientMessageId: 'bootstrap-admission', createdAt: '2026-01-01T00:00:00Z',
    });
    pending.resolve(snapshot());
    await loading;
    expect(view.controller.store.snapshot.cursor).toBe('cursor:initial');
    expect(view.controller.store.visibleItems).toEqual(expect.arrayContaining([
      expect.objectContaining({ content: 'Local admission during bootstrap' }),
    ]));
  });

  it('reconnect reset replaces the old backfill cursor once, shared across returning consumers', async () => {
    const client = api();
    client.snapshot.mockResolvedValueOnce({
      ...snapshot(), timeline: { items: [], before_cursor: 'previous-lineage', has_more_before: true },
    });
    const view = acquireTimeline(scope, client);
    await view.controller.load();
    client.sync.mockResolvedValue({ ...delta(), reset_required: true, reset_reason: 'cursor_expired' });
    const sameScope = acquireTimeline(scope, client);
    await Promise.all([view.controller.load(), sameScope.controller.load()]);
    expect(client.sync).toHaveBeenCalledTimes(1);
    expect(client.snapshot).toHaveBeenCalledTimes(2);
    expect(sameScope.controller.store.snapshot.beforeCursor).toBeNull();
    expect(sameScope.controller.store.snapshot.hasMoreBefore).toBe(false);
  });

  it('rejects foreign-scope device data and evicts inactive residency above twenty scopes', async () => {
    device.rows.set(`timeline:${scope.key}`, {
      state: { ...emptyChatV2State(), cursor: 'foreign', scopeKey: 'session:other' },
    });
    const client = api();
    const view = acquireTimeline(scope, client);
    await view.controller.hydrate();
    expect(view.controller.store.snapshot.cursor).toBeNull();
    view.release();
    for (let n = 0; n < 30; n += 1) acquireTimeline(conversationTimelineScope(`fixture-${n}`), client).release();
    expect(timelineResourceCounts()).toEqual({ entries: 20, retained: 0 });
  });

  it('fences delayed history after another consumer replaces the lineage with the same projection version', async () => {
    const client = api();
    client.snapshot.mockResolvedValueOnce({
      ...snapshot(), timeline: { items: [], before_cursor: 'before-reset', has_more_before: true },
    });
    const historyView = acquireTimeline(scope, client);
    const resetView = acquireTimeline(scope, client);
    await historyView.controller.load();
    const delayed = deferred<TimelineBackfillResponse>();
    client.timeline.mockReturnValueOnce(delayed.promise);
    const obsolete = historyView.controller.older('before-reset');
    const rejected = expect(obsolete).rejects.toMatchObject({ name: 'AbortError' });
    client.sync.mockResolvedValue({ ...delta(), reset_required: true, reset_reason: 'cursor_expired' });
    client.snapshot.mockResolvedValue({
      ...snapshot(), cursor: 'cursor:replacement',
      timeline: { items: [], before_cursor: 'before-replacement', has_more_before: true },
    });
    await resetView.controller.load();
    const replacement = resetView.controller.store.snapshot;
    expect(client.timeline.mock.calls[0][1].signal.aborted).toBe(true);
    delayed.resolve({
      schema_version: 2, projection_version: 'test', scope,
      conversation_id: scope.conversation_id!, before_cursor: 'stale-pagination',
      has_more_before: true, server_time: '', items: [{
        id: 'obsolete-history', kind: 'message', role: 'assistant', message_id: 'obsolete-history',
        content: 'Must not cross the reset', sort_key: '0001', source_refs: [], stable: true,
        status: 'complete', attachments: [], partial: false,
      }],
    });
    await rejected;
    expect(historyView.controller.store.snapshot).toBe(replacement);
    expect(historyView.controller.store.snapshot.beforeCursor).toBe('before-replacement');
    expect(device.rows.get(`timeline:${scope.key}`)).toMatchObject({
      state: { cursor: 'cursor:replacement', beforeCursor: 'before-replacement', timelineItems: [] },
    });
    client.timeline.mockResolvedValueOnce({
      schema_version: 2, projection_version: 'test', scope, conversation_id: scope.conversation_id!,
      before_cursor: null, has_more_before: false, server_time: '', items: [],
    });
    await historyView.controller.older('before-reset');
    expect(client.timeline).toHaveBeenCalledTimes(2);
  });

  it('bounds nonadvancing sync and preserves typed errors instead of retrying snapshots', async () => {
    const client = api();
    const view = acquireTimeline(scope, client);
    await view.controller.load();
    client.sync.mockResolvedValue({ ...delta(), has_more: true });
    await expect(view.controller.load()).rejects.toThrow('no progress');
    expect(view.controller.phase).toBe('error');
    expect(client.sync).toHaveBeenCalledTimes(1);
    expect(client.snapshot).toHaveBeenCalledTimes(1);
  });
});
