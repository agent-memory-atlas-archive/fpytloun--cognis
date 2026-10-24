import { expect, it } from 'vitest';
import { canonicalMetadata, durableMatch } from '../../../e2e/canonical-response-evidence';
import type { MessageTimelineItem, TimelineScope } from './types';

const scope: TimelineScope = { key: 'conversation:fixture', kind: 'conversation', conversation_id: 'fixture' };
const item: MessageTimelineItem = {
  id: 'user:fixture-message', kind: 'message', role: 'user', client_message_id: 'fixture-message', stable: true,
  message_id: 'fixture-message', sort_key: '0001', partial: false,
  content: 'must not be retained', attachments: [{ artifact_id: 'must-not-be-retained',
    kind: 'file', mime_type: 'text/plain', filename: 'must-not-be-retained.txt', size_bytes: 1 }],
  source_refs: [{ store: 'intaris', session_id: 'fixture-session', seq: 7, event_type: 'user_message' }],
};
it('buffers sanitized canonical evidence before client identity is known', () => {
  const early = canonicalMetadata({
    scope,
    timeline: { items: [item] }, cursor: 'opaque-token',
  });
  expect(durableMatch(early, 'fixture-message', 'conversation:fixture')?.id).toBe(item.id);
  expect(JSON.stringify(early)).not.toContain('must');
  expect(JSON.stringify(early)).not.toContain('opaque-token');
  expect(durableMatch(early, 'other', 'conversation:fixture')).toBeUndefined();
  expect(durableMatch(early, 'fixture-message', 'conversation:other')).toBeUndefined();
});
it('rejects runtime overlays, unstable items and non-durable source references', () => {
  expect(durableMatch(canonicalMetadata({ scope, runtime: { volatile_items: [item] } }), 'fixture-message', 'conversation:fixture'))
    .toBeUndefined();
  for (const changed of [{ ...item, stable: false }, { ...item, source_refs: [] },
    { ...item, role: 'assistant' as const }, { ...item, id: '' },
    { ...item, source_refs: [{ store: 'runtime', session_id: 'fixture', seq: 0, event_type: 'user_message' }] }]) {
    expect(durableMatch(canonicalMetadata({ scope, ops: [{ op: 'upsert_item', item: changed }] }), 'fixture-message', 'conversation:fixture'))
      .toBeUndefined();
  }
});
it('accepts stable sync upserts and backfill items without storing payload data', () => {
  for (const body of [{ ops: [{ op: 'upsert_item' as const, item }] }, { items: [item] }]) {
    expect(durableMatch(canonicalMetadata({ ...body, scope }), 'fixture-message', 'conversation:fixture')?.refs).toHaveLength(1);
  }
});
