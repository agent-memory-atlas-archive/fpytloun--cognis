import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import ScopeReplacementHarness from './ScopeReplacementHarness.svelte';
import { expect, it, vi } from 'vitest';
import ScopedChatV2Timeline from './ScopedChatV2Timeline.svelte';
import type { ChatSnapshot, TimelineScope } from '$lib/chat-v2/types';
import { offlineCache } from '$lib/offline/cache';
import { acquireTimeline, clearTimelineMemory } from '$lib/chat-v2/timeline-controller.svelte';

it('renders an isolated provider conflict and retries only after the sibling closes', async () => {
  vi.spyOn(offlineCache, 'currentOwner', 'get').mockReturnValue('provider-fixture@cognis.test');
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal('IntersectionObserver', class { observe() {} unobserve() {} disconnect() {} });
  const scope: TimelineScope = { kind: 'conversation', key: 'conversation:provider-fixture', conversation_id: 'provider-fixture' };
  const snapshot = {
    schema_version: 2, projection_version: 'test', scope,
    conversation: { conversation_id: scope.conversation_id, agent_id: 'synthetic-agent', status: 'active' },
    cursor: 'provider-cursor', server_time: '',
    timeline: { items: [], has_more_before: false, before_cursor: null },
    state: { state_version: 1, active_turn: {}, pending: {}, active_session: {}, capabilities: [] },
    queue: { messages: [], queued_count: 0 }, runtime: null,
  } as unknown as ChatSnapshot;
  const firstApi = { snapshot: vi.fn().mockResolvedValue(snapshot), sync: vi.fn(), timeline: vi.fn() };
  const replacementSnapshot = { ...snapshot, timeline: { ...snapshot.timeline, items: [{
    id: 'user:replacement-provider', kind: 'message', role: 'user',
    message_id: 'replacement-provider', client_message_id: 'replacement-provider',
    content: 'Replacement provider canonical content', sort_key: '0001',
    status: 'complete', stable: true, partial: false, attachments: [], source_refs: [],
  }] } };
  const secondApi = { snapshot: vi.fn().mockResolvedValue(replacementSnapshot), sync: vi.fn(), timeline: vi.fn() };
  const sibling = acquireTimeline(scope, firstApi);
  const realtime = { subscribe: vi.fn(() => () => {}), acquireChatV2: vi.fn(), releaseChatV2: vi.fn(), updateChatV2Cursor: vi.fn() };
  const view = render(ScopedChatV2Timeline, { scope, api: secondApi, realtime, autoBackfill: false });
  try {
    await screen.findByText('This timeline is open with another API provider. Close the other view and retry.');
    expect(sibling.controller.current).toBe(true);
    expect(secondApi.snapshot).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await tick();
    expect(sibling.controller.current).toBe(true);
    expect(secondApi.snapshot).not.toHaveBeenCalled();
    expect(realtime.acquireChatV2).not.toHaveBeenCalled();
    sibling.release();
    await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(secondApi.snapshot).toHaveBeenCalledOnce());
    await screen.findByText('Replacement provider canonical content');
    expect(firstApi.snapshot).not.toHaveBeenCalled();
  } finally {
    sibling.release();
    view.unmount();
    clearTimelineMemory();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  }
});

it.each(['direct', 'parent'] as const)('recovers recipient messages and retains equivalent scope (%s)', async (mode) => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal('IntersectionObserver', class { observe() {} unobserve() {} disconnect() {} });
  const scope: TimelineScope = {
    kind: 'conversation', key: 'conversation:recipient-fixture', conversation_id: 'recipient-fixture',
  };
  const snapshot = {
    schema_version: 2, projection_version: 'test', scope,
    conversation: { conversation_id: scope.conversation_id, agent_id: 'synthetic-agent', status: 'active' },
    cursor: 'cursor:before', server_time: '',
    timeline: { has_more_before: false, before_cursor: null, items: [{
      id: 'handoff:preserved', kind: 'handoff', text: 'Expanded handoff fixture detail',
      focus: 'preserved expansion', sort_key: '0000', status: 'complete',
      stable: true, source_refs: [],
    }] },
    state: { state_version: 1, active_turn: {}, pending: {}, active_session: {}, capabilities: [] },
    queue: { messages: [], queued_count: 0 }, runtime: null,
  } as unknown as ChatSnapshot;
  let listener: (event: unknown) => void = () => {};
  const unsubscribe = vi.fn();
  const api = {
    snapshot: vi.fn().mockResolvedValue(snapshot),
    sync: vi.fn().mockResolvedValue({
      schema_version: 2, projection_version: 'test', scope, conversation_id: scope.conversation_id,
      cursor_before: 'cursor:before', cursor_after: 'cursor:after',
      ops: [{ op: 'upsert_item', item: {
        id: 'user:remote-admission', kind: 'message', role: 'user', message_id: 'remote-admission',
        client_message_id: 'remote-admission', content: 'Independent sender fixture',
        sort_key: '0001', status: 'complete', stable: true,
        source_refs: [{ store: 'intaris', session_id: 'recipient-session', seq: 1, event_type: 'user_message' }],
        attachments: [], partial: false,
      } }],
      reset_required: false, has_more: false, server_time: '',
    }),
    timeline: vi.fn(),
  };
  const realtime = {
    subscribe: (next: typeof listener) => { listener = next; return unsubscribe; },
    acquireChatV2: vi.fn(), releaseChatV2: vi.fn(), updateChatV2Cursor: vi.fn(),
  };
  const props = { scope, api, realtime, autoBackfill: false };
  const view = mode === 'parent'
    ? render(ScopeReplacementHarness, { initial: props })
    : render(ScopedChatV2Timeline, props);
  try {
    await waitFor(() => expect(realtime.acquireChatV2).toHaveBeenCalled());
    listener({ type: 'scope_invalidated', reason: 'event_store_session_invalidated', revision: 'admission-1' });
    await screen.findByText('Independent sender fixture');
    expect(api.snapshot).toHaveBeenCalledOnce();
    expect(api.sync).toHaveBeenCalledOnce();
    expect(screen.getAllByText('Independent sender fixture')).toHaveLength(1);
    const expansion = screen.getByRole('button', { name: 'Handoff preserved expansion' });
    await fireEvent.click(expansion);
    expect(expansion).toHaveAttribute('aria-expanded', 'true');
    const expandedDetail = screen.getByText('Expanded handoff fixture detail');
    if (mode === 'parent') await fireEvent.click(screen.getByText('Replace equivalent scope'));
    else await view.rerender({ scope: { ...scope }, api, realtime, autoBackfill: false });
    await tick();
    expect(realtime.releaseChatV2).not.toHaveBeenCalled();
    expect(realtime.acquireChatV2).toHaveBeenCalledOnce();
    expect(api.snapshot).toHaveBeenCalledOnce();
    expect(api.sync).toHaveBeenCalledOnce();
    expect(screen.getAllByText('Independent sender fixture')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Handoff preserved expansion' })).toBe(expansion);
    expect(expansion).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Expanded handoff fixture detail')).toBe(expandedDetail);
    if (mode === 'direct') {
      const replacedApi = {
        snapshot: vi.fn().mockResolvedValue(snapshot),
        sync: vi.fn().mockImplementation((_scope, cursor) => Promise.resolve({
          schema_version: 2, projection_version: 'test', scope,
          cursor_before: cursor, cursor_after: cursor, ops: [], reset_required: false,
          has_more: false, server_time: '',
        })),
        timeline: vi.fn(),
      };
      await view.rerender({ ...props, api: replacedApi });
      await waitFor(() => expect(realtime.releaseChatV2).toHaveBeenCalledTimes(1));
      await waitFor(() => expect(realtime.acquireChatV2).toHaveBeenCalledTimes(2));
      await waitFor(() => expect(
        replacedApi.sync.mock.calls.length + replacedApi.snapshot.mock.calls.length
      ).toBeGreaterThan(0));
      expect(api.sync).toHaveBeenCalledOnce();
      expect(unsubscribe).toHaveBeenCalledOnce();
      let replacementListener: typeof listener = () => {};
      const replacementUnsubscribe = vi.fn();
      const replacedRealtime = {
        ...realtime, acquireChatV2: vi.fn(), releaseChatV2: vi.fn(),
        subscribe: vi.fn((next: typeof listener) => {
          replacementListener = next;
          return replacementUnsubscribe;
        }),
      };
      await view.rerender({ ...props, api: replacedApi, realtime: replacedRealtime });
      await waitFor(() => expect(replacedRealtime.acquireChatV2).toHaveBeenCalledOnce());
      expect(realtime.releaseChatV2).toHaveBeenCalledTimes(2);
      expect(unsubscribe).toHaveBeenCalledTimes(2);
      const requestCount = replacedApi.sync.mock.calls.length;
      replacementListener({ type: 'scope_invalidated', scope_key: scope.key,
        conversation_id: scope.conversation_id, reason: 'chat_scope_changed', revision: 'new-provider' });
      await waitFor(() => expect(replacedApi.sync.mock.calls.length).toBeGreaterThan(requestCount));
      expect(api.sync).toHaveBeenCalledOnce();
    }
  } finally {
    view.unmount();
    vi.unstubAllGlobals();
  }
});

it('renders recovered canonical history with runtime arriving during its held snapshot', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('No network allowed'); }));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal('IntersectionObserver', class { observe() {} unobserve() {} disconnect() {} });
  const scope: TimelineScope = {
    kind: 'session', key: 'session:reset-diagnostic',
    session_id: 'reset-diagnostic', conversation_id: 'reset-conversation',
  };
  const snapshot = (content: string, cursor: string) => ({
    schema_version: 2, projection_version: 'test', scope,
    conversation: { conversation_id: scope.conversation_id, agent_id: 'synthetic-agent', status: 'active' },
    cursor, server_time: '',
    timeline: { has_more_before: false, before_cursor: null, items: [{
      id: 'diagnostic-row', kind: 'message', role: 'assistant', message_id: 'diagnostic-row',
      content, sort_key: '0001', status: 'complete', stable: true, source_refs: [], attachments: [], partial: false,
    }] },
    state: { state_version: 1, active_turn: {}, pending: {}, active_session: {}, capabilities: [] },
    queue: { messages: [], queued_count: 0 }, runtime: null,
  }) as unknown as ChatSnapshot;
  let listener: (event: unknown) => void = () => {};
  let resolve!: (value: ChatSnapshot) => void;
  const pending = new Promise<ChatSnapshot>(done => { resolve = done; });
  const api = {
    snapshot: vi.fn().mockResolvedValueOnce(snapshot('Old canonical fixture', 'cursor:initial')).mockReturnValue(pending),
    sync: vi.fn().mockResolvedValue({
      schema_version: 2, projection_version: 'test', scope, conversation_id: scope.conversation_id,
      cursor_before: 'cursor:initial', cursor_after: 'cursor:initial', ops: [],
      reset_required: true, reset_reason: 'cursor_expired', has_more: false, server_time: '',
    }),
    timeline: vi.fn(),
  };
  const realtime = {
    subscribe: (next: typeof listener) => { listener = next; return () => {}; },
    acquireChatV2: vi.fn(), releaseChatV2: vi.fn(), updateChatV2Cursor: vi.fn(),
  };
  const view = render(ScopedChatV2Timeline, { scope, api, realtime, autoBackfill: false });
  try {
    await screen.findByText('Old canonical fixture');
    listener({
      type: 'chat_v2_frame', schema_version: 2, projection_version: 'test', scope,
      conversation_id: scope.conversation_id, cursor_before: 'cursor:foreign', cursor_after: 'cursor:gap',
      ops: [{ op: 'upsert_item', item: snapshot('Gap fixture', 'cursor:gap').timeline.items[0] }], runtime: null,
    });
    await waitFor(() => expect(api.snapshot).toHaveBeenCalledTimes(2));
    listener({
      type: 'chat_v2_frame', schema_version: 2, projection_version: 'test', scope,
      conversation_id: scope.conversation_id, cursor_before: 'cursor:subscription', cursor_after: 'cursor:subscription',
      ops: [], runtime: {
        runtime_epoch: 'synthetic-epoch', runtime_revision: 1, generated_at: '',
        has_active_turn: false, active_turn: null, volatile_items: [], cycle_states: [],
      },
    });
    resolve(snapshot('Recovered canonical fixture', 'cursor:recovered'));
    await screen.findByText('Recovered canonical fixture');
    expect(screen.queryByText('Old canonical fixture')).toBeNull();
    expect(api.snapshot).toHaveBeenCalledTimes(2);
    expect(api.sync).toHaveBeenCalledOnce();
  } finally {
    view.unmount();
    vi.unstubAllGlobals();
  }
});
