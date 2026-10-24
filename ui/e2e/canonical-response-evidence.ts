import { Buffer } from 'node:buffer';
import type { ChatSnapshot, ChatSyncResponse, TimelineBackfillResponse, TimelineItem } from '../src/lib/chat-v2/types';

type EvidenceResponse = Partial<Pick<ChatSnapshot, 'scope' | 'cursor'>
  & Pick<ChatSyncResponse, 'conversation_id' | 'cursor_after' | 'ops'>
  & Pick<TimelineBackfillResponse, 'items'>> & {
    timeline?: Pick<ChatSnapshot['timeline'], 'items'>;
    runtime?: Pick<ChatSnapshot['runtime'], 'volatile_items'>;
  };

/** Fixture-only metadata. Never retain content, attachments or encoded cursors. */
export function canonicalMetadata(body: EvidenceResponse) {
  const item = (value: TimelineItem) => ({
    id: value.id, client_message_id: value.kind === 'message' ? value.client_message_id : undefined,
    kind: value.kind, role: value.kind === 'message' ? value.role : undefined,
    stable: value.stable === true,
    refs: (value.source_refs ?? []).map(ref => ({
      store: ref.store, session_id: ref.session_id, seq: ref.seq, event_type: ref.event_type,
    })),
  });
  const canonical = [
    ...(body.timeline?.items ?? []),
    ...(body.items ?? []),
    ...(body.ops ?? []).filter(op => op.op === 'upsert_item').map(op => op.item),
  ];
  const runtime = [
    ...(body.runtime?.volatile_items ?? []),
  ];
  let position: unknown = null;
  const encoded = body.cursor_after ?? body.cursor;
  if (typeof encoded === 'string') {
    try {
      const decoded = JSON.parse(Buffer.from(encoded.split('.')[0], 'base64url').toString());
      position = {
        scope_key: decoded.scope_key, conversation_id: decoded.conversation_id,
        view_revision: decoded.view_revision,
        session_watermarks: decoded.session_watermarks?.map((mark: any) => ({
          store: mark.store, session_id: mark.session_id, last_seq: mark.last_seq,
        })),
      };
    } catch { /* Unknown cursor format is not a persistence witness. */ }
  }
  return {
    scope_key: body.scope?.key, conversation_id: body.conversation_id ?? body.scope?.conversation_id,
    position,
    canonical: canonical.slice(-128).map(item),
    runtime: runtime.slice(-128).map(item),
  };
}

export type CanonicalMetadata = ReturnType<typeof canonicalMetadata>;

export function durableMatch(evidence: CanonicalMetadata, clientId: string, scopeKey: string) {
  if (evidence.scope_key !== scopeKey) return undefined;
  return evidence.canonical.find(item => item.kind === 'message' && item.role === 'user'
    && typeof item.id === 'string' && item.id.length > 0
    && item.client_message_id === clientId && item.stable
    && item.refs.some(ref => ref.store === 'intaris' && typeof ref.session_id === 'string'
      && ref.session_id.length > 0 && Number.isInteger(ref.seq) && ref.seq >= 0
      && ref.event_type === 'user_message'));
}
