import type { ChatV2ClientState } from './sync-engine';
import type { TimelineItem } from './types';

const sortKeyPattern = /^(\d{4}):(\d{15}):(\d{6}):(\d{2}):(\d{9})$/;
const unchanged = (item: TimelineItem): TimelineItem => item;

function turnId(item: TimelineItem): string | null {
  return 'turn_id' in item ? item.turn_id ?? null : null;
}

function isExecution(item: TimelineItem): boolean {
  return item.kind === 'tool_call' || item.kind === 'thinking'
    || (item.kind === 'message' && item.role === 'assistant');
}

function isDurable(item: TimelineItem): boolean {
  return item.stable && item.source_refs.length > 0
    && item.source_refs.every(ref => ref.store === 'intaris' && Number.isSafeInteger(ref.seq) && ref.seq > 0);
}

/** Place proven historical fallbacks before a partial window, not after live work.
 * This is a presentation bucket, not recovered canonical provenance or chronology.
 * Never pass these copies back into reconciliation or persistence.
 */
export function localHistoryPlacement(
  state: ChatV2ClientState,
  canonicalIds: ReadonlySet<string>,
  canonicalClientIds: ReadonlySet<string>,
): (item: TimelineItem) => TimelineItem {
  const head = state.timelineItems[0];
  if (state.scope?.kind !== 'conversation' || !state.hasMoreBefore || !head || !isDurable(head)) return unchanged;
  const headKey = sortKeyPattern.exec(head.sort_key);
  if (!headKey || Number(headKey[2]) <= 0) return unchanged;

  const headTurn = turnId(head);
  const activeTurn = state.runtime?.has_active_turn ? state.runtime.active_turn?.turn_id : null;
  const headTurnIsClosed = Boolean(headTurn && headTurn !== activeTurn && isExecution(head)
    && state.timelineItems.slice(1).some(item =>
      isDurable(item) && isExecution(item) && turnId(item) && turnId(item) !== headTurn));
  const headSessions = new Set(head.source_refs.map(ref => ref.session_id));
  const headSession = headSessions.size === 1 ? head.source_refs[0].session_id : null;
  const runtimeIds = new Set(state.runtime?.volatile_items.map(item => item.id));
  const queuedClientIds = new Set(state.queue?.messages.map(message => message.client_message_id));
  const prefix = `${headKey[1]}:${String(Number(headKey[2]) - 1).padStart(15, '0')}`;

  return item => {
    if (item.stable !== false || canonicalIds.has(item.id) || runtimeIds.has(item.id)) return item;
    const key = sortKeyPattern.exec(item.sort_key);
    if (!key || !/^999[5-9]$/.test(key[1]) || key[2] !== '999999999999999') return item;

    let beforeWindow = false;
    if (item.kind === 'message' && item.role === 'user') {
      const clientId = item.client_message_id;
      beforeWindow = Boolean(
        clientId && item.id === `user:${clientId}` && item.message_id === `client:${clientId}`
        && item.status === 'complete' && item.turn_id === headTurn && headTurnIsClosed
        && !canonicalClientIds.has(clientId) && !queuedClientIds.has(clientId)
        && (!state.admissionPlacements[clientId] || state.admissionPlacements[clientId].placement === 'timeline'),
      );
    } else if (item.kind === 'compaction') {
      beforeWindow = item.status === 'compacted' && Boolean(item.previous_session_id)
        && item.previous_session_id !== item.session_id && Boolean(headSession) && item.session_id === headSession;
    }
    if (!beforeWindow) return item;

    // Suffixes retain deterministic fallback ordering, not inferred event order.
    const sort_key = `${prefix}:${key[3]}:${key[4]}:${key[5]}`;
    return sort_key < head.sort_key ? { ...item, sort_key } : item;
  };
}
