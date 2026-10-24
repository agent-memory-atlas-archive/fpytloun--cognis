import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { normalizeNotification, notificationPath } from '../src/lib/notification-events';
import type { CognisWebSocketEvent } from '../src/lib/types/api';

const event = JSON.parse(readFileSync('../.local/platform-sidebar-replay.json', 'utf8'));
assert.equal(event.type, 'sidebar_conversation_upsert');
assert.ok(event.conversation.conversation_id);
// Actual captured owner-wide row, with explicitly injected terminal state.
// This is not evidence that a real LLM completed or UNUserNotificationCenter delivered.
const terminal = { ...event, conversation: { ...event.conversation,
  has_unread: true, has_active_turn: false, context: { ...event.conversation.context, type: 'web' },
  last_message_at: event.conversation.created_at,
} } as CognisWebSocketEvent;
const intent = normalizeNotification(terminal);
assert.ok(intent);
assert.deepEqual(intent, normalizeNotification(terminal));
assert.equal(notificationPath(intent), `/chat/${event.conversation.conversation_id}`);
assert.equal(normalizeNotification({ ...terminal, conversation: { ...(terminal as any).conversation,
  has_active_turn: true } } as CognisWebSocketEvent), null);
assert.ok(!JSON.stringify(intent).includes(event.conversation.title));
console.log('PASS: captured canonical sidebar shape; injected final/nonfinal replay and stable safe identity');
