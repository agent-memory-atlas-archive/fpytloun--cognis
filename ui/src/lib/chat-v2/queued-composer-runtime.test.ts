import { expect, it } from 'vitest';
import { queuedComposerRuntime } from '../../../e2e/queued-composer-runtime';
import { ChatV2Store } from './store.svelte';
import { deriveChatV2ViewProjection } from '../chat-page';
import type { ChatSnapshot, ChatSyncResponse } from './types';

it('restores the real fixture running turn after cache neutralization at the same epoch/revision', () => {
  const id = 'conv-task-chat';
  const fields = queuedComposerRuntime(id);
  const snapshot: ChatSnapshot = {
    schema_version: 2, projection_version: 'composer-regression',
    conversation: { conversation_id: id, agent_id: 'agent-stage39', status: 'active',
      active_session_id: fields.runtime.active_turn!.session_id },
    timeline: { items: [], has_more_before: false, before_cursor: null },
    ...fields, queue: { messages: [], queued_count: 0 },
    cursor: 'composer-regression', server_time: fields.runtime.generated_at,
  };
  expect(snapshot.runtime.has_active_turn).toBe(snapshot.runtime.active_turn !== null);
  expect(snapshot.state.active_turn).toEqual(snapshot.runtime.active_turn);
  expect(snapshot.state.active_session.session_id).toBe(snapshot.conversation.active_session_id);
  const original = new ChatV2Store();
  original.replaceFromSnapshot(snapshot);
  const cached = original.serializeState({ settleRuntimeOverlay: true });
  expect(cached.runtime).toMatchObject({ has_active_turn: false, active_turn: null,
    runtime_epoch: fields.runtime.runtime_epoch, runtime_revision: fields.runtime.runtime_revision });
  const sync: ChatSyncResponse = {
    schema_version: 2, projection_version: snapshot.projection_version, conversation_id: id,
    cursor_before: snapshot.cursor, cursor_after: snapshot.cursor, ops: [],
    runtime: fields.runtime, reset_required: false, has_more: false, server_time: snapshot.server_time,
  };
  const reopened = new ChatV2Store();
  reopened.restoreState(cached);
  reopened.applySync(sync);
  expect(reopened.snapshot.runtime?.active_turn).toEqual(fields.runtime.active_turn);
  expect(deriveChatV2ViewProjection(reopened.snapshot).turnInProgress).toBe(true);

  // Characterize the old invalid fixture, not an alternate production algorithm.
  const invalid = new ChatV2Store();
  invalid.restoreState(cached);
  invalid.applySync({ ...sync, runtime: { ...fields.runtime, active_turn: null } });
  expect(deriveChatV2ViewProjection(invalid.snapshot).turnInProgress).toBe(false);
});
