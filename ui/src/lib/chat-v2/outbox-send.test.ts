import { beforeEach, describe, expect, it, vi } from 'vitest';
import 'fake-indexeddb/auto';

const mocks = vi.hoisted(() => ({
  sendMessage: vi.fn(),
  executeCommand: vi.fn(),
  resolveAll: vi.fn(async (refs: unknown[]) => refs.map((ref) => ({ ...(ref as object), artifact_id: 'art_uploaded' }))),
  forget: vi.fn(),
}));

vi.mock('./api', () => ({
  chatV2Api: { sendMessage: mocks.sendMessage, executeCommand: mocks.executeCommand },
}));
vi.mock('./attachment-uploads', () => ({
  attachmentUploads: { resolveAll: mocks.resolveAll, forget: mocks.forget, isDurable: async () => true },
  isLocalAttachment: (ref: { local_id?: string }) => Boolean(ref.local_id),
  toServerAttachment: (ref: object) => ref,
}));

import { MemoryChatV2Outbox as RawMemoryOutbox, CoordinatedOutbox, type OutboxEntry } from './outbox';
import { documentCoordination } from '$lib/document-coordination';
import { drainConversationOutbox } from './outbox-send';

function entry(id: string, createdAt: string, extra: Partial<OutboxEntry> = {}): OutboxEntry {
  return {
    client_txn_id: id,
    client_message_id: `m-${id}`,
    conversation_id: 'conv-1',
    content: id,
    attachments: [],
    status: 'pending',
    created_at: createdAt,
    updated_at: createdAt,
    ...extra,
  };
}

const admittedResponse = { kind: 'accepted' };
function MemoryChatV2Outbox() {
  // A shared durable-store stand-in; real IndexedDB is exercised in WK tests.
  const shared = new RawMemoryOutbox();
  shared.isDurable = () => true;
  return new CoordinatedOutbox(shared, documentCoordination());
}

describe('drainConversationOutbox', () => {
  beforeEach(async () => {
    localStorage.clear();
    await documentCoordination().beginLogin();
    await documentCoordination().verified('outbox@cognis.test');
    mocks.sendMessage.mockReset();
    mocks.executeCommand.mockReset();
    mocks.resolveAll.mockClear();
    mocks.forget.mockClear();
  });

  it('sends in order and stops at a transient failure so later messages never overtake', async () => {
    const outbox = MemoryChatV2Outbox();
    await outbox.put(entry('b', '2026-01-01T00:00:02Z'));
    await outbox.put(entry('a', '2026-01-01T00:00:01Z'));
    await outbox.put(entry('c', '2026-01-01T00:00:03Z'));
    mocks.sendMessage
      .mockResolvedValueOnce(admittedResponse)
      .mockRejectedValueOnce(Object.assign(new TypeError('Failed to fetch'), { status: 0 }));
    const admitted: string[] = [];
    const failed: Array<[string, boolean]> = [];

    const result = await drainConversationOutbox({
      outbox,
      conversationId: 'conv-1',
      isCurrent: () => true,
      onAdmitted: (item) => { admitted.push(item.client_txn_id); },
      onFailed: (item, _error, retryable) => { failed.push([item.client_txn_id, retryable]); },
    });

    expect(admitted).toEqual(['a']);
    expect(failed).toEqual([['b', true]]);
    expect(result).toEqual({ sentAny: true, retryRemaining: true });
    expect(mocks.sendMessage).toHaveBeenCalledTimes(2);
    // Receipts settle queued sibling windows without duplicating a network send.
    expect(await outbox.get('a')).toMatchObject({ status: 'acked', admitted: admittedResponse });
    expect(await outbox.get('b')).toMatchObject({ status: 'failed', retryable: true });
  });

  it('skips permanent rejections and finishes uploads before sending', async () => {
    const outbox = MemoryChatV2Outbox();
    await outbox.put(entry('a', '2026-01-01T00:00:01Z', { retryable: false }));
    await outbox.put(entry('b', '2026-01-01T00:00:02Z', {
      attachments: [{ artifact_id: 'local:x', local_id: 'x', kind: 'image', mime_type: 'image/png', filename: 'p.png', size_bytes: 1 }],
    }));
    mocks.sendMessage.mockResolvedValue(admittedResponse);

    const result = await drainConversationOutbox({
      outbox,
      conversationId: 'conv-1',
      isCurrent: () => true,
      onAdmitted: () => undefined,
    });

    expect(result.retryRemaining).toBe(false);
    expect(mocks.sendMessage).toHaveBeenCalledTimes(1);
    const [, txnId, body] = mocks.sendMessage.mock.calls[0];
    expect(txnId).toBe('b');
    expect(body.attachments).toEqual([expect.objectContaining({ artifact_id: 'art_uploaded' })]);
  });

  it('sends stored content verbatim as a message, never as a command', async () => {
    const outbox = MemoryChatV2Outbox();
    // A one-shot "/plan /yolo on" is stored as content "/yolo on" with plan mode.
    await outbox.put(entry('a', '2026-01-01T00:00:01Z', { content: '/yolo on', chat_mode: 'plan' }));
    mocks.sendMessage.mockResolvedValue(admittedResponse);

    await drainConversationOutbox({ outbox, conversationId: 'conv-1', isCurrent: () => true, onAdmitted: () => undefined });

    expect(mocks.executeCommand).not.toHaveBeenCalled();
    expect(mocks.sendMessage).toHaveBeenCalledWith('conv-1', 'a', expect.objectContaining({
      content: '/yolo on',
      chat_mode: 'plan',
      client_message_id: 'm-a',
    }));
  });

  it('reports a failure even after the view stopped being current', async () => {
    const outbox = MemoryChatV2Outbox();
    await outbox.put(entry('a', '2026-01-01T00:00:01Z'));
    let current = true;
    mocks.sendMessage.mockImplementation(async () => {
      current = false; // the modal closes while the request is in flight
      throw Object.assign(new Error('rejected'), { status: 422 });
    });
    const onFailed = vi.fn();

    await drainConversationOutbox({
      outbox,
      conversationId: 'conv-1',
      isCurrent: () => current,
      onAdmitted: () => undefined,
      onFailed,
    });

    expect(onFailed).toHaveBeenCalledWith(expect.objectContaining({ client_txn_id: 'a' }), expect.any(Error), false);
  });

  it('reports the in-flight entry for the whole send, including attachment uploads', async () => {
    const outbox = MemoryChatV2Outbox();
    await outbox.put(entry('a', '2026-01-01T00:00:01Z', {
      attachments: [{ artifact_id: 'local:x', local_id: 'x', kind: 'image', mime_type: 'image/png', filename: 'p.png', size_bytes: 1 }],
    }));
    const seen: Array<string | null> = [];
    let inFlightDuringUpload: string | null = 'unset';
    let current: string | null = null;
    mocks.resolveAll.mockImplementationOnce(async (refs: unknown[]) => {
      inFlightDuringUpload = current;
      return refs.map((ref) => ({ ...(ref as object), artifact_id: 'art_uploaded' }));
    });
    mocks.sendMessage.mockResolvedValue(admittedResponse);

    await drainConversationOutbox({
      outbox,
      conversationId: 'conv-1',
      isCurrent: () => true,
      onAdmitted: () => undefined,
      onInFlight: (item) => { current = item?.client_txn_id ?? null; seen.push(current); },
    });

    expect(inFlightDuringUpload).toBe('a');
    expect(seen).toEqual(['a', null]);
  });

  it('tolerates owned entries without attachments without authorizing unowned legacy data', async () => {
    const legacy = entry('a', '2026-01-01T00:00:01Z');
    delete (legacy as Partial<OutboxEntry>).attachments;
    const outbox = MemoryChatV2Outbox();
    await outbox.put(legacy);
    mocks.sendMessage.mockResolvedValue(admittedResponse);

    await drainConversationOutbox({ outbox, conversationId: 'conv-1', isCurrent: () => true, onAdmitted: () => undefined });

    expect(mocks.sendMessage.mock.calls[0][2].attachments).toEqual([]);
  });
});
