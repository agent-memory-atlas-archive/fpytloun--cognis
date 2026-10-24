import { afterEach, describe, expect, it, vi } from 'vitest';
import { IDBFactory } from 'fake-indexeddb';
import 'fake-indexeddb/auto';
import { DocumentCoordination, CoordinationUnavailableError, StaleDocumentError, type CoordinationEnvironment } from '$lib/document-coordination';
import { TestWebLocks } from '../../test/web-locks';
import { DocumentDrafts } from './document-drafts';
import { inspectRetainedData } from './quarantine';
import { CoordinatedOutbox, MemoryChatV2Outbox, type OutboxEntry } from '$lib/chat-v2/outbox';
import { drainConversationOutbox, sendOutboxEntry, projectAdmissionFailure } from '$lib/chat-v2/outbox-send';
import { dispatchChatComposerMessage } from '$lib/chat-v2/composer-dispatch';
import type { SendMessageV2Response } from '$lib/chat-v2/types';
import { AttachmentUploadManager } from '$lib/chat-v2/attachment-uploads';
import { AttachmentBlobStore, type StoredAttachmentBlob } from '$lib/chat-v2/attachment-blobs';
import type { AttachmentRef } from '$lib/types/api';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
async function documents(locks: TestWebLocks | undefined = new TestWebLocks()) {
  localStorage.clear();
  const listeners = new Set<() => void>();
  let generation = 'one';
  const indexedDB = new IDBFactory();
  const mount = () => new DocumentCoordination({
    storage: localStorage, indexedDB, locks: locks as unknown as LockManager,
    profile: () => 'https://document-fixture.invalid', generation: () => generation,
    uuid: () => crypto.randomUUID(),
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    publish() { [...listeners].forEach((listener) => listener()); },
  });
  const a = mount(), b = mount();
  await Promise.all([a.initialize(), b.initialize()]);
  await a.verified('first@cognis.test'); await b.verified('first@cognis.test');
  return { a, b, changeGeneration() { generation = 'two'; } };
}
const entry: OutboxEntry = {
  client_txn_id: 'txn-retained', client_message_id: 'message-retained',
  conversation_id: 'conversation-fixture', content: 'fixture only', attachments: [],
  status: 'pending', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
};
const response: SendMessageV2Response = {
  status: 'accepted', client_txn_id: entry.client_txn_id, client_message_id: entry.client_message_id,
  conversation_id: entry.conversation_id, server_time: entry.created_at,
};

describe('application operations across documents', () => {
  afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

  it('cold constructors do not publish competing epochs and initialization converges without logout', async () => {
    localStorage.clear();
    const locks = new TestWebLocks();
    const listeners = new Set<() => void>();
    const environment: CoordinationEnvironment = {
      storage: localStorage, locks: locks as unknown as LockManager,
      profile: () => 'https://cold.coordination.invalid', generation: () => 'generation',
      uuid: () => crypto.randomUUID(),
      subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
      publish() { listeners.forEach((listener) => listener()); },
    };
    const a = new DocumentCoordination(environment), b = new DocumentCoordination(environment);
    const revokedA = vi.fn(), revokedB = vi.fn();
    a.onInvalidated(revokedA); b.onInvalidated(revokedB);
    expect(localStorage.length).toBe(0);
    await a.initialize();
    await a.verified('cold@coordination.invalid');
    const lease = a.capture();
    await b.initialize();
    await b.verified('cold@coordination.invalid');
    lease.assertCurrent();
    expect(a.owner).toBe(b.owner);
    expect(revokedA).not.toHaveBeenCalled();
    expect(revokedB).not.toHaveBeenCalled();
    await b.invalidate();
    await expect(lease.validate()).rejects.toThrow(StaleDocumentError);
    const reopened = new DocumentCoordination(environment);
    await reopened.initialize();
    expect(reopened.blocked).toBe(true);
    expect(reopened.owner).toBeNull();
    a.dispose(); b.dispose(); reopened.dispose();
  });

  it('preserves unsent draft across reload when IndexedDB cannot open, without admission or recovery reads', async () => {
    const { a, b } = await documents();
    const drafts = new DocumentDrafts(() => a, () => localStorage);
    drafts.read('draft:unavailable-db');
    await drafts.write('draft:unavailable-db', 'unsent input');
    const inner = new MemoryChatV2Outbox();
    const get = vi.spyOn(inner, 'get').mockRejectedValue(new Error('database unavailable'));
    vi.spyOn(inner, 'put').mockRejectedValue(new Error('database unavailable'));
    const page = new CoordinatedOutbox(inner, a);
    // Main's prepare-before-clear boundary: persistence failure exits before
    // dispatch/projection. Reading the failed DB cannot be a recovery prerequisite.
    await expect(page.put(entry)).rejects.toThrow('database unavailable');
    expect(get).not.toHaveBeenCalled();
    expect(new DocumentDrafts(() => b, () => localStorage).read('draft:unavailable-db')).toBe('unsent input');
    a.dispose(); b.dispose();
  });

  it('a delayed page failure cannot downgrade a sibling receipt or cause another send', async () => {
    const { a, b } = await documents();
    const shared = new MemoryChatV2Outbox(); shared.isDurable = () => true;
    const page = new CoordinatedOutbox(shared, a), sibling = new CoordinatedOutbox(shared, b);
    await page.put(entry);
    await expect(sendOutboxEntry(page, (await page.get(entry.client_txn_id))!,
      async () => { throw new Error('offline'); })).rejects.toThrow('offline');
    const send = vi.fn(async () => response);
    await sendOutboxEntry(sibling, (await sibling.get(entry.client_txn_id))!, send);
    // The pre-fix page's delayed catch at +page.svelte:8627. This must not
    // overwrite the terminal receipt even if an old consumer still calls it.
    await page.update(entry.client_txn_id, { status: 'failed', retryable: true });
    await drainConversationOutbox({ outbox: sibling, conversationId: entry.conversation_id,
      sendMessage: send, isCurrent: () => true, onAdmitted: () => {} });
    expect(send).toHaveBeenCalledTimes(1);
    expect(await page.get(entry.client_txn_id)).toMatchObject({ status: 'acked', admitted: response });
    const failureUI = vi.fn(), successUI = vi.fn();
    await projectAdmissionFailure(page, entry, failureUI, successUI);
    expect(failureUI).not.toHaveBeenCalled();
    expect(successUI).toHaveBeenCalledOnce();
    await page.put(entry);
    await page.delete(entry.client_txn_id);
    expect(await page.get(entry.client_txn_id)).toMatchObject({ status: 'acked', admitted: response });
    a.dispose(); b.dispose();
  });

  it('projects a genuine failure before sibling admission without restoring or changing its transaction', async () => {
    const { a, b } = await documents();
    const shared = new MemoryChatV2Outbox(); shared.isDurable = () => true;
    const page = new CoordinatedOutbox(shared, a), sibling = new CoordinatedOutbox(shared, b);
    await page.put(entry);
    await expect(sendOutboxEntry(page, (await page.get(entry.client_txn_id))!,
      async () => { throw new Error('offline'); })).rejects.toThrow('offline');
    const pending = vi.fn(), admitted = vi.fn();
    await projectAdmissionFailure(page, entry, pending, admitted);
    expect(pending.mock.calls[0][0]).toMatchObject({ status: 'failed', client_txn_id: entry.client_txn_id });
    expect(admitted).not.toHaveBeenCalled();
    const send = vi.fn(async () => response);
    await sendOutboxEntry(sibling, (await sibling.get(entry.client_txn_id))!, send);
    await b.invalidate();
    expect(await projectAdmissionFailure(page, entry, pending, admitted)).toBe('stale');
    expect(pending).toHaveBeenCalledOnce();
    expect(admitted).not.toHaveBeenCalled();
    a.dispose(); b.dispose();
  });

  it('serializes an actual direct send against a sibling drainer and keeps one receipt/txn', async () => {
    const { a, b } = await documents();
    const shared = new MemoryChatV2Outbox();
    shared.isDurable = () => true; // Shared durable-store stand-in, not a lock-only test.
    const first = new CoordinatedOutbox(shared, a), second = new CoordinatedOutbox(shared, b);
    await first.put(entry);
    const network = deferred<typeof response>();
    const send = vi.fn((_conversation: string, _txn: string, _body: unknown) => network.promise);
    const direct = dispatchChatComposerMessage({
      conversationId: entry.conversation_id, content: entry.content,
      clientTxnId: entry.client_txn_id, clientMessageId: entry.client_message_id,
      attachments: entry.attachments,
    }, { outbox: first, sendMessage: send });
    await vi.waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    const drain = drainConversationOutbox({ outbox: second, conversationId: entry.conversation_id,
      sendMessage: send, isCurrent: () => true, onAdmitted: () => {} });
    network.resolve(response);
    await Promise.all([direct, drain]);
    expect(send).toHaveBeenCalledTimes(1);
    expect(send.mock.calls[0][1]).toBe(entry.client_txn_id);
    expect(await second.get(entry.client_txn_id)).toMatchObject({ status: 'acked', admitted: response });
    a.dispose(); b.dispose();
  });

  it('logout cancels queued admission; late network completion cannot acknowledge or touch another account', async () => {
    const { a, b } = await documents();
    const shared = new MemoryChatV2Outbox(); shared.isDurable = () => true;
    const first = new CoordinatedOutbox(shared, a), second = new CoordinatedOutbox(shared, b);
    await first.put(entry);
    const network = deferred<typeof response>();
    const send = vi.fn((_conversation: string, _txn: string, _body: unknown) => network.promise);
    const direct = sendOutboxEntry(first, (await first.get(entry.client_txn_id))!, send);
    const stale = expect(direct).rejects.toBeInstanceOf(StaleDocumentError);
    await vi.waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    const drain = drainConversationOutbox({ outbox: second, conversationId: entry.conversation_id,
      sendMessage: send, isCurrent: () => true, onAdmitted: () => {} }).catch(() => undefined);
    await b.invalidate();
    await b.verified('second@cognis.test');
    network.resolve(response);
    await stale; await drain;
    expect(send).toHaveBeenCalledTimes(1);
    expect(await shared.get(entry.client_txn_id)).toMatchObject({ status: 'sending', client_txn_id: entry.client_txn_id });
    expect(() => first.lease.assertCurrent()).toThrow(StaleDocumentError);
    a.dispose(); b.dispose();
  });

  it('retains stale edits while preventing stale clear/overwrite of a newer draft', async () => {
    const { a, b, changeGeneration } = await documents();
    const first = new DocumentDrafts(() => a), second = new DocumentDrafts(() => b);
    first.read('composer'); second.read('composer');
    await first.write('composer', 'first');
    expect(second.read('composer')).toBe('first');
    await second.write('composer', 'newer');
    await first.removeIfValue('composer', 'first');
    await first.write('composer', 'stale edit');
    expect(second.read('composer')).toBe('newer');
    const retained = Object.keys(localStorage).filter((key) => key.includes(':retained:'));
    expect(retained).toHaveLength(1);
    expect(localStorage.getItem(retained[0])).toBe('stale edit');
    changeGeneration();
    expect(() => first.write('composer', 'wrong generation')).toThrow(StaleDocumentError);
    a.dispose(); b.dispose();
  });

  it('overlapping upload owners share one receipt; prune cannot remove another window files', async () => {
    const { a, b } = await documents();
    const rows = new Map<string, StoredAttachmentBlob>();
    const blobs = Object.assign(new AttachmentBlobStore(undefined), {
      put: async (row: StoredAttachmentBlob) => { rows.set(row.local_id, row); return true; },
      get: async (id: string) => rows.get(id) ?? null,
      delete: async (id: string) => { rows.delete(id); },
      prune: vi.fn(async () => {}),
    });
    const pending = deferred<AttachmentRef>();
    const upload = vi.fn(() => pending.promise);
    const first = new AttachmentUploadManager(blobs, upload, () => crypto.randomUUID(),
      () => ({ lease: a.capture(), coordination: a, blobs }));
    const second = new AttachmentUploadManager(blobs, upload, () => crypto.randomUUID(),
      () => ({ lease: b.capture(), coordination: b, blobs }));
    const ref = first.stage(new File(['fixture bytes'], 'fixture.txt', { type: 'text/plain' }));
    const one = first.resolve(ref);
    await vi.waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    const two = second.resolve(ref);
    await second.prune([]);
    expect(rows.has(ref.local_id!)).toBe(true);
    expect(blobs.prune).not.toHaveBeenCalled();
    const result = { artifact_id: 'fixture-upload-result', kind: 'file', mime_type: 'text/plain',
      filename: 'fixture.txt', size_bytes: 13 };
    pending.resolve(result);
    expect(await one).toMatchObject(result);
    expect(await two).toMatchObject(result);
    expect(upload).toHaveBeenCalledTimes(1);
    expect(rows.get(ref.local_id!)?.result).toMatchObject(result);
    a.dispose(); b.dispose();
  });

  it('an interrupted upload cannot be silently repeated by a sibling window', async () => {
    const { a, b } = await documents();
    const rows = new Map<string, StoredAttachmentBlob>();
    const blobs = Object.assign(new AttachmentBlobStore(undefined), {
      put: async (row: StoredAttachmentBlob) => { rows.set(row.local_id, row); return true; },
      get: async (id: string) => rows.get(id) ?? null,
      delete: async (id: string) => { rows.delete(id); }, prune: async () => {},
    });
    const pending = deferred<AttachmentRef>();
    const upload = vi.fn(() => pending.promise);
    const first = new AttachmentUploadManager(blobs, upload, () => crypto.randomUUID(),
      () => ({ lease: a.capture(), coordination: a, blobs }));
    const ref = first.stage(new File(['retained'], 'retained.txt'));
    const oldResult = first.resolve(ref).catch(() => undefined);
    await vi.waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    await b.invalidate();
    await b.verified('first@cognis.test');
    const next = new AttachmentUploadManager(blobs, upload, () => crypto.randomUUID(),
      () => ({ lease: b.capture(), coordination: b, blobs }));
    const rejected = expect(next.resolve(ref)).rejects.toMatchObject({ code: 'upload_outcome_uncertain' });
    // A transport that ignores abort must settle before the old lock is
    // released; otherwise a second request could overlap it.
    pending.resolve({ artifact_id: 'late-fixture-result', kind: 'file', filename: 'retained.txt',
      mime_type: 'application/octet-stream', size_bytes: 8 });
    await oldResult;
    await rejected;
    expect(upload).toHaveBeenCalledTimes(1);
    expect(rows.get(ref.local_id!)?.blob).toBeTruthy();
    a.dispose(); b.dispose();
  });

  it('does not expose a previous account draft or infer ownership for raw legacy data', async () => {
    const { a, b } = await documents();
    localStorage.setItem('cognis-draft:conversation', 'unknown author bytes');
    const old = new DocumentDrafts(() => a);
    expect(old.read('cognis-draft:conversation')).toBeNull();
    await old.write('cognis-draft:conversation', 'owned first account');
    await b.invalidate(); await b.verified('second@cognis.test');
    const next = new DocumentDrafts(() => b);
    expect(next.read('cognis-draft:conversation')).toBeNull();
    await next.write('cognis-draft:conversation', 'owned second account');
    await a.synchronize();
    expect(() => old.read('cognis-draft:conversation')).toThrow(StaleDocumentError);
    expect(localStorage.getItem('cognis-draft:conversation')).toBe('unknown author bytes');
    a.dispose(); b.dispose();
  });

  it('crash/retry of namespace migration leaves legacy bytes and IDs unchanged', async () => {
    const legacy = 'unknown \u017elu\u0165ou\u010dk\u00fd bytes';
    localStorage.setItem('cognis-draft:retained', legacy);
    const names = vi.fn(async () => [{ name: 'cognis-chat-v2', version: 1 }]);
    const factory = { databases: names } as unknown as IDBFactory;
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => { throw new Error('quota'); });
    await expect(inspectRetainedData(localStorage, factory)).rejects.toThrow('quota');
    set.mockRestore();
    await inspectRetainedData(localStorage, factory);
    await inspectRetainedData(localStorage, factory);
    expect(localStorage.getItem('cognis-draft:retained')).toBe(legacy);
    expect(localStorage.getItem('cognis-retained-unowned:v2')).toBe('retained');
    expect(names).toHaveBeenCalledTimes(2);
  });

  it('rejects unsupported coordination and a late identity response instead of unsafe fallback', async () => {
    const { a, b } = await documents();
    await expect(a.verified('different@cognis.test')).rejects.toThrow(StaleDocumentError);
    a.dispose(); b.dispose();
    const owner = new DocumentCoordination({
      storage: localStorage, locks: undefined, profile: () => 'https://unsupported.invalid', generation: () => '',
      uuid: () => crypto.randomUUID(), subscribe: () => () => {}, publish: () => {},
    });
    await expect(owner.initialize()).rejects.toThrow(CoordinationUnavailableError);
    expect(() => owner.capture()).toThrow(CoordinationUnavailableError);
    owner.dispose();
  });
});
