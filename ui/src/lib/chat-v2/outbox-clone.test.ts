import { describe, expect, it, vi } from 'vitest';
import { IDBFactory, IDBObjectStore } from 'fake-indexeddb';
import { IndexedDbChatV2Outbox, type OutboxEntry } from './outbox';
import { reactiveAttachments } from './attachment-state-test-fixture.svelte';

const attachment = () => new Proxy({
  artifact_id: 'local:synthetic-image', local_id: 'synthetic-image',
  kind: 'image', filename: 'synthetic.png', mime_type: 'image/png', size_bytes: 1,
}, {});
const entry = (): OutboxEntry => ({
  client_txn_id: 'clone-regression', client_message_id: 'clone-message',
  conversation_id: 'clone-conversation', content: 'Synthetic image',
  attachments: [attachment()], status: 'pending',
  created_at: '2026-10-20T00:00:00Z', updated_at: '2026-10-20T00:00:00Z',
});
const lease = {
  owner: 'synthetic-profile', epoch: 'synthetic-epoch',
  signal: new AbortController().signal, assertCurrent() {}, async validate() {},
};

describe('durable outbox structured clone boundary', () => {
  it('establishes that array spreading does not make proxy metadata cloneable', () => {
    expect(() => structuredClone([...entry().attachments])).toThrow();
  });
  it('persists supported proxy metadata without an event-handler abort', async () => {
    const outbox = new IndexedDbChatV2Outbox(new IDBFactory(), 'clone-put', lease);
    await expect(outbox.put(entry())).resolves.toBeUndefined();
    expect((await outbox.get('clone-regression'))?.attachments[0]).toEqual(attachment());
  });
  it('updates supported proxy metadata without an event-handler abort', async () => {
    const outbox = new IndexedDbChatV2Outbox(new IDBFactory(), 'clone-update', lease);
    await outbox.put({ ...entry(), attachments: [] });
    await expect(outbox.update('clone-regression', { attachments: [attachment()] })).resolves.toBeUndefined();
  });
  it('persists actual compiled Svelte reactive metadata and all receipt fields', async () => {
    const outbox = new IndexedDbChatV2Outbox(new IDBFactory(), 'clone-svelte', lease);
    const source = entry();
    source.attachments = reactiveAttachments([{
      ...attachment(), url: null, duration_seconds: 0, voice_recording: false,
      blob_url: 'blob:synthetic-preview', upload_state: 'failed',
      upload_progress: 0.5, upload_error: 'synthetic failure',
    }]);
    expect(() => structuredClone(source.attachments)).toThrow();
    await outbox.put(source);
    const admitted = new Proxy({
      status: 'accepted' as const, client_txn_id: source.client_txn_id,
      client_message_id: source.client_message_id, conversation_id: source.conversation_id,
      server_time: source.created_at,
    }, {});
    await outbox.update(source.client_txn_id, { admitted, status: 'acked', retryable: false, last_error: null });
    expect(await outbox.get(source.client_txn_id)).toMatchObject({
      ...source, updated_at: expect.any(String), admitted, status: 'acked', retryable: false, last_error: null,
    });
  });
  it('aborts a callback write and returns its original cause without a partial row or fallback', async () => {
    const outbox = new IndexedDbChatV2Outbox(new IDBFactory(), 'clone-original-cause', lease);
    const failure = new DOMException('Synthetic callback write failure', 'DataCloneError');
    const put = vi.spyOn(IDBObjectStore.prototype, 'put').mockImplementation(() => { throw failure; });
    try {
      await expect(outbox.put({ ...entry(), attachments: [] })).rejects.toBe(failure);
      expect(outbox.isDurable()).toBe(true);
      expect(await outbox.get('clone-regression')).toBeNull();
    } finally { put.mockRestore(); }
  });
  it('leaves the old row unchanged when an update callback fails', async () => {
    const outbox = new IndexedDbChatV2Outbox(new IDBFactory(), 'clone-update-cause', lease);
    await outbox.put({ ...entry(), attachments: [] });
    const failure = new Error('Synthetic storage failure');
    const put = vi.spyOn(IDBObjectStore.prototype, 'put').mockImplementation(() => { throw failure; });
    try {
      // Content is now immutable. Exercise the same callback-abort boundary
      // through a supported mutable status field instead.
      await expect(outbox.update('clone-regression', { status: 'sending' })).rejects.toBe(failure);
      expect((await outbox.get('clone-regression'))?.content).toBe('Synthetic image');
      expect((await outbox.get('clone-regression'))?.status).toBe('pending');
    } finally { put.mockRestore(); }
  });
});
