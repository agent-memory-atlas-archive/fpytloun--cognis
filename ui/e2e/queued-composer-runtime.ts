import type { ChatSnapshot, RuntimeActiveTurn } from '../src/lib/chat-v2/types';

/** Coherent running-turn fields shared by snapshot and sync fixture responses. */
export function queuedComposerRuntime(conversationId: string): Pick<ChatSnapshot, 'state' | 'runtime'> {
  const activeTurn: RuntimeActiveTurn = {
    turn_id: `turn-${conversationId}`,
    session_id: `session-${conversationId}`,
    status: 'running',
  };
  return {
    runtime: {
      runtime_epoch: 'composer-regression',
      runtime_revision: 1,
      generated_at: '2030-04-16T12:00:00Z',
      has_active_turn: activeTurn !== null,
      active_turn: activeTurn,
      volatile_items: [],
    },
    state: {
      state_version: 1,
      snapshot_generated_at: '2030-04-16T12:00:00Z',
      capabilities: [],
      active_turn: { ...activeTurn },
      active_session: { session_id: activeTurn.session_id, status: 'running' },
      pending: {},
    },
  };
}
