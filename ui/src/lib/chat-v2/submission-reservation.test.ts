import { expect, it, vi } from 'vitest';
import 'fake-indexeddb/auto';
import { IDBFactory } from 'fake-indexeddb';
import { CoordinatedOutbox, IndexedDbChatV2Outbox, type OutboxEntry } from './outbox';
import { documentCoordination } from '$lib/document-coordination';
import { sendOutboxEntry } from './outbox-send';

const lease = { owner: 'reservation-owner', epoch: 'reservation-epoch',
  signal: new AbortController().signal, assertCurrent() {}, async validate() {} };
function proposal(): OutboxEntry {
  return { client_txn_id: crypto.randomUUID(), client_message_id: crypto.randomUUID(),
    conversation_id: 'reservation-conversation', content: 'same input', attachments: [],
    status: 'pending', created_at: '2026-10-20T00:00:00Z', updated_at: '2026-10-20T00:00:00Z' };
}
const binding = { version: 1 as const, draft_key: 'reservation-draft', input_revision: 'input-first',
  input: { text: 'same input', attachments: [], chat_mode: null } };

it('atomically binds concurrent documents to one immutable pair of IDs', async () => {
  const factory = new IDBFactory();
  const first = new IndexedDbChatV2Outbox(factory, 'reservation-race', lease);
  const second = new IndexedDbChatV2Outbox(factory, 'reservation-race', lease);
  const [a, b] = await Promise.all([first.reserve(proposal(), binding), second.reserve(proposal(), binding)]);
  expect(a.client_txn_id).toBe(b.client_txn_id);
  expect(a.client_message_id).toBe(b.client_message_id);
  expect(a.status).toBe('preparing');
  expect(await first.list()).toHaveLength(1);
});

it('does not reset a receipt on reservation retry and fails closed on revision mismatch', async () => {
  const outbox = new IndexedDbChatV2Outbox(new IDBFactory(), 'reservation-receipt', lease);
  const row = await outbox.reserve(proposal(), binding);
  await outbox.activate(row.client_txn_id, []);
  await outbox.update(row.client_txn_id, { status: 'sending' });
  expect((await outbox.reserve(proposal(), binding)).status).toBe('sending');
  await expect(outbox.reserve(proposal(), { ...binding, input: { ...binding.input, text: 'different' } }))
    .rejects.toThrow('input');
});

it('returns the activation winner unchanged and never admits preparation through generic updates', async () => {
  const outbox = new IndexedDbChatV2Outbox(new IDBFactory(), 'reservation-activation', lease);
  const row = await outbox.reserve(proposal(), binding);
  await expect(outbox.update(row.client_txn_id, { status: 'pending' })).rejects.toThrow();
  const [a, b] = await Promise.all([outbox.activate(row.client_txn_id, []), outbox.activate(row.client_txn_id, [])]);
  expect(a).toEqual(b);
  expect(a.status).toBe('pending');
});

it('returns one activation winner across separate database connections', async () => {
  const factory = new IDBFactory();
  const first = new IndexedDbChatV2Outbox(factory, 'activation-documents', lease);
  const second = new IndexedDbChatV2Outbox(factory, 'activation-documents', lease);
  const row = await first.reserve(proposal(), binding);
  const [a, b] = await Promise.all([
    first.activate(row.client_txn_id, []), second.activate(row.client_txn_id, []),
  ]);
  expect(a).toEqual(b);
  expect(a.submission).toEqual(binding);
  expect(await second.get(row.client_txn_id)).toEqual(a);
});

it('preserves accepted receipts and canonical IDs on reserve, activation and generic update retries', async () => {
  const outbox = new IndexedDbChatV2Outbox(new IDBFactory(), 'immutable-receipt', lease);
  const row = await outbox.reserve(proposal(), binding);
  await outbox.activate(row.client_txn_id, []);
  const admitted = {
    status: 'accepted' as const, client_txn_id: row.client_txn_id, client_message_id: row.client_message_id,
    conversation_id: row.conversation_id, server_time: row.created_at,
  };
  await outbox.update(row.client_txn_id, { status: 'acked', admitted });
  const accepted = await outbox.get(row.client_txn_id);
  expect(await outbox.reserve(proposal(), binding)).toEqual(accepted);
  expect(await outbox.activate(row.client_txn_id, [])).toEqual(accepted);
  await outbox.update(row.client_txn_id, { status: 'pending', admitted: undefined });
  expect(await outbox.get(row.client_txn_id)).toEqual(accepted);
  await expect(outbox.update(row.client_txn_id, { client_message_id: crypto.randomUUID() })).rejects.toThrow('Immutable');
  await expect(outbox.update(row.client_txn_id, { submission: { ...binding, input_revision: 'replacement-intent' } })).rejects.toThrow('Immutable');
});

it('does not downgrade an in-flight bound row to pending through generic updates', async () => {
  const outbox = new IndexedDbChatV2Outbox(new IDBFactory(), 'immutable-sending', lease);
  const row = await outbox.reserve(proposal(), binding);
  await outbox.activate(row.client_txn_id, []);
  await outbox.update(row.client_txn_id, { status: 'sending' });
  // A stale generic writer cannot turn an ambiguous/in-flight send into a
  // freshly pending entry. Returning unchanged is sufficient at this boundary.
  const beforeDowngrade = await outbox.get(row.client_txn_id);
  await outbox.update(row.client_txn_id, { status: 'pending', last_error: 'stale writer', retryable: true });
  expect(await outbox.get(row.client_txn_id)).toEqual(beforeDowngrade);
  expect(await outbox.get(row.client_txn_id)).toMatchObject({
    status: 'sending', client_txn_id: row.client_txn_id, client_message_id: row.client_message_id,
    submission: binding,
  });
});

it('records a bound send failure and retries through the send owner with the same IDs', async () => {
  const owner = documentCoordination();
  await owner.initialize();
  await owner.invalidate(false);
  await owner.verified('bound-retry@cognis.test');
  const outbox = new CoordinatedOutbox(
    new IndexedDbChatV2Outbox(indexedDB, crypto.randomUUID(), owner.capture()), owner);
  const reserved = await outbox.reserve(proposal(), binding);
  const row = await outbox.activate(reserved.client_txn_id, []);
  const response = { status: 'accepted' as const, client_txn_id: row.client_txn_id,
    client_message_id: row.client_message_id, conversation_id: row.conversation_id,
    server_time: row.created_at };
  const transport = vi.fn()
    .mockRejectedValueOnce(new TypeError('Synthetic network failure'))
    .mockResolvedValue(response);
  await expect(sendOutboxEntry(outbox, row, transport)).rejects.toThrow('Synthetic network failure');
  expect(await outbox.get(row.client_txn_id)).toMatchObject({
    status: 'failed', submission: binding, client_message_id: row.client_message_id,
  });
  await sendOutboxEntry(outbox, row, transport);
  const accepted = await outbox.get(row.client_txn_id);
  expect(accepted).toMatchObject({ status: 'acked', admitted: response, submission: binding });
  await sendOutboxEntry(outbox, row, transport);
  expect(transport).toHaveBeenCalledTimes(2);
  for (const call of transport.mock.calls) {
    expect(call[1]).toBe(row.client_txn_id);
    expect(call[2].client_message_id).toBe(row.client_message_id);
  }
  expect(await outbox.get(row.client_txn_id)).toEqual(accepted);
});
