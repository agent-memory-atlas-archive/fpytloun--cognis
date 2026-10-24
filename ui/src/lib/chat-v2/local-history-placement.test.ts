import { describe, expect, it } from 'vitest';
import { ChatV2Store } from './store.svelte';
import { applyBackfill, emptyChatV2State, visibleTimelineItems, type ChatV2ClientState } from './sync-engine';
import { conversationTimelineScope, sessionTimelineScope, type ChatSnapshot, type TimelineItem } from './types';

function fixture(): ChatV2ClientState {
  const scope = conversationTimelineScope('history-placement');
  const head: TimelineItem = {
    id: 'message:head', kind: 'message', role: 'assistant', message_id: 'head',
    content: 'Earlier execution', attachments: [], partial: false,
    stable: true, status: 'complete', turn_id: 'earlier-turn',
    sort_key: '0002:000000000000274:000188:02:000000000',
    source_refs: [{ store: 'intaris', session_id: 'rotated-session', seq: 274, event_type: 'assistant_message' }],
  };
  return {
    ...emptyChatV2State(), scope, scopeKey: scope.key, conversationId: 'history-placement',
    projectionVersion: 'chat-v2-test', hasMoreBefore: true, beforeCursor: 'history-window-before', syncStatus: 'ready',
    timelineItems: [head, {
      ...head, id: 'message:latest', message_id: 'latest', turn_id: 'current-turn',
      sort_key: '0003:000000000000030:000001:02:000000000', content: 'Latest execution',
      source_refs: [{ store: 'intaris', session_id: 'current-session', seq: 30, event_type: 'assistant_message' }],
    }],
    localItems: [{
      id: 'user:earlier-admission', kind: 'message', role: 'user',
      message_id: 'client:earlier-admission', client_message_id: 'earlier-admission',
      content: 'Earlier admission', attachments: [], partial: false,
      stable: false, status: 'complete', turn_id: 'earlier-turn', source_refs: [],
      sort_key: '9996:999999999999999:000000:00:000000000',
    }, {
      id: 'compaction:earlier', kind: 'compaction', status: 'compacted', stable: false,
      session_id: 'rotated-session', previous_session_id: 'previous-session', method: 'llm',
      turns_compacted: 2, summary_preview: '',
      sort_key: '9996:999999999999999:000158:10:000000000',
      source_refs: [{ store: 'runtime', session_id: 'rotated-session', seq: 0, event_type: 'compaction' }],
    }],
    runtime: {
      runtime_epoch: 'current-epoch', runtime_revision: 1, generated_at: '2026-01-02T00:00:00Z',
      has_active_turn: true, active_turn: { turn_id: 'current-turn', session_id: 'current-session', status: 'running' },
      volatile_items: [],
    },
  };
}

describe('local history boundary placement', () => {
  it('places captured settled admission and rotation fallbacks before the bounded window, without changing raw state', () => {
    const state = fixture();
    const before = structuredClone(state);
    const visible = visibleTimelineItems(state);
    expect(visible.map(item => item.id)).toEqual([
      ...state.localItems.map(item => item.id), ...state.timelineItems.map(item => item.id),
    ]);
    expect(visible.map(item => item.sort_key)).toEqual([...visible.map(item => item.sort_key)].sort());
    expect(visible.slice(2)).toEqual(state.timelineItems);
    expect(visible[0]).toEqual({ ...state.localItems[0], sort_key: '0002:000000000000273:000000:00:000000000' });
    expect(visible[1]).toEqual({ ...state.localItems[1], sort_key: '0002:000000000000273:000158:10:000000000' });
    expect(visibleTimelineItems(state)).toBe(visible);
    expect(state).toEqual(before);
  });

  it('recomputes after cache hydration and never serializes presentation keys', () => {
    const store = new ChatV2Store();
    store.restoreState(fixture());
    const expected = [...fixture().localItems, ...fixture().timelineItems].map(item => item.id);
    for (let i = 0; i < 3; i++) {
      expect(store.visibleItems.map(item => item.id)).toEqual(expected);
      const saved = store.serializeState();
      expect(saved.localItems.map(item => item.sort_key)).toEqual(fixture().localItems.map(item => item.sort_key));
      store.restoreState(saved);
    }
  });

  it('does not blink back to sentinel placement when a smaller fresh snapshot follows cache hydration', () => {
    const cached = fixture();
    const store = new ChatV2Store();
    const fresh: ChatSnapshot = {
      schema_version: 2, projection_version: 'chat-v2-test', scope: cached.scope!,
      conversation: { conversation_id: 'history-placement', agent_id: 'history-agent', status: 'active' },
      server_time: '2026-01-02T00:00:01Z', cursor: 'fresh-tail-cursor',
      timeline: { items: cached.timelineItems.slice(-1), has_more_before: true, before_cursor: 'before-fresh-tail' },
      state: { state_version: 1, snapshot_generated_at: '', capabilities: [], active_turn: {}, pending: {}, active_session: {} },
      runtime: cached.runtime!, queue: { messages: [], queued_count: 0 },
    };
    store.restoreState(cached);
    const expected = [...cached.localItems, ...cached.timelineItems].map(item => item.id);
    for (let i = 0; i < 3; i++) {
      expect(store.visibleItems.map(item => item.id)).toEqual(expected);
      store.replaceFromSnapshot(fresh);
      expect(store.visibleItems.map(item => item.id)).toEqual(expected);
      expect(store.snapshot.timelineItems).toEqual(cached.timelineItems);
      const saved = store.serializeState({ settleRuntimeOverlay: true });
      expect(saved.localItems.map(item => item.sort_key)).toEqual(cached.localItems.map(item => item.sort_key));
      store.restoreState(saved);
    }
  });

  it('lets incremental backfill replace the bucket with exact canonical order and provenance once', () => {
    const initial = fixture();
    visibleTimelineItems(initial);
    const canonical = initial.localItems.map((item, i) => ({
      ...item, stable: true,
      sort_key: i === 0 ? '0001:000000000000607:000000:00:000000000' : '0001:000000000001097:000158:10:000000000',
      source_refs: [{ store: 'intaris' as const, session_id: 'previous-session', seq: i === 0 ? 607 : 1097, event_type: i === 0 ? 'user_message' : 'lifecycle' }],
    }));
    const recovered = applyBackfill(initial, {
      schema_version: 2, projection_version: 'chat-v2-test', conversation_id: 'history-placement',
      server_time: '2026-01-02T00:00:00Z', items: canonical, has_more_before: false,
    });
    const visible = visibleTimelineItems(recovered);
    expect(visible.map(item => item.id)).toEqual([...canonical, ...initial.timelineItems].map(item => item.id));
    expect(visible.slice(0, 2)).toEqual(canonical);
  });

  const commonNoOps: [string, (state: ChatV2ClientState) => void][] = [
    ['exhausted history', state => { state.hasMoreBefore = false; }],
    ['session scope', state => { state.scope = sessionTimelineScope('rotated-session'); }],
    ['empty history', state => { state.timelineItems = []; }],
    ['malformed head key', state => { state.timelineItems[0].sort_key = '0002:274'; }],
    ['zero head sequence', state => { state.timelineItems[0].sort_key = '0002:000000000000000:000188:02:000000000'; }],
    ['non-durable head', state => { state.timelineItems[0].source_refs[0].store = 'runtime'; }],
    ['unstable head', state => { state.timelineItems[0].stable = false; }],
    ['stable locals', state => { state.localItems.forEach(item => { item.stable = true; }); }],
    ['non-sentinel sequence', state => { state.localItems.forEach(item => { item.sort_key = item.sort_key.replace('999999999999999', '000000000000001'); }); }],
    ['unrecognized band', state => { state.localItems.forEach(item => { item.sort_key = item.sort_key.replace('9996:', '9994:'); }); }],
    ['current runtime membership', state => { state.runtime!.volatile_items = structuredClone(state.localItems); }],
  ];
  it.each(commonNoOps)('does not infer placement from %s', (_label, modify) => {
    const state = fixture();
    modify(state);
    const visible = visibleTimelineItems(state);
    for (const local of state.localItems) {
      expect(visible.find(item => item.id === local.id)?.sort_key).toBe(local.sort_key);
    }
  });

  const admissionNoOps: [string, (state: ChatV2ClientState) => void][] = [
    ['pending', state => { state.localItems[0].status = 'pending'; }],
    ['unidentified', state => { if (state.localItems[0].kind === 'message') state.localItems[0].client_message_id = null; }],
    ['not admission-shaped', state => { if (state.localItems[0].kind === 'message') state.localItems[0].message_id = 'context-message'; }],
    ['missing turn', state => { if ('turn_id' in state.localItems[0]) state.localItems[0].turn_id = null; }],
    ['different head turn', state => { if ('turn_id' in state.localItems[0]) state.localItems[0].turn_id = 'unrelated-turn'; }],
    ['still-active head turn', state => { state.runtime!.active_turn!.turn_id = 'earlier-turn'; }],
    ['queued turn-ID admission', state => {
      state.admissionPlacements['earlier-admission'] = { placement: 'queue', status: 'complete' };
    }],
    ['explicit queue membership', state => {
      state.queue = { queued_count: 1, messages: [{ queue_id: 'queued-admission', client_message_id: 'earlier-admission', content: '', attachments: [], position: 0 }] };
    }],
    ['later user admission only', state => {
      if (state.timelineItems[1].kind === 'message') state.timelineItems[1].role = 'user';
    }],
    ['no later different-turn progress', state => { if ('turn_id' in state.timelineItems[1]) state.timelineItems[1].turn_id = 'earlier-turn'; }],
  ];
  it.each(admissionNoOps)('preserves a %s without moving it before prior execution', (_label, modify) => {
    const state = fixture();
    modify(state);
    const local = state.localItems[0];
    expect(visibleTimelineItems(state).find(item => item.id === local.id)?.sort_key).toBe(local.sort_key);
  });

  const compactionNoOps: [string, (state: ChatV2ClientState) => void][] = [
    ...(['running', 'failed', 'skipped'] as const).map(status => [status, (state: ChatV2ClientState) => { state.localItems[1].status = status; }] as [string, (state: ChatV2ClientState) => void]),
    ['same-session rotation', state => { if (state.localItems[1].kind === 'compaction') state.localItems[1].previous_session_id = 'rotated-session'; }],
    ['unknown previous session', state => { if (state.localItems[1].kind === 'compaction') state.localItems[1].previous_session_id = null; }],
    ['target session mismatch', state => { if (state.localItems[1].kind === 'compaction') state.localItems[1].session_id = 'unrelated-session'; }],
    ['ambiguous head session', state => {
      state.timelineItems[0].source_refs.push({ store: 'intaris', session_id: 'another-session', seq: 40, event_type: 'assistant_message' });
    }],
  ];
  it.each(compactionNoOps)('preserves %s compaction placement', (_label, modify) => {
    const state = fixture();
    modify(state);
    const local = state.localItems[1];
    expect(visibleTimelineItems(state).find(item => item.id === local.id)?.sort_key).toBe(local.sort_key);
  });
});
