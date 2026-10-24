import { auth } from '../src/lib/stores/auth';
import { DocumentCoordination, documentCoordination } from '../src/lib/document-coordination';
import { createIndexedDbChatV2Outbox, type ChatV2Outbox } from '../src/lib/chat-v2/outbox';
import { sendOutboxEntry, drainConversationOutbox, projectAdmissionFailure } from '../src/lib/chat-v2/outbox-send';
import { DocumentDrafts } from '../src/lib/offline/document-drafts';
import { inspectRetainedData } from '../src/lib/offline/quarantine';
import { AttachmentUploadManager } from '../src/lib/chat-v2/attachment-uploads';
import { AttachmentBlobStore, ATTACHMENT_UPLOADS_DB_NAME } from '../src/lib/chat-v2/attachment-blobs';
import type { AttachmentRef } from '../src/lib/types/api';
import type { SendMessageV2Response } from '../src/lib/chat-v2/types';

if (!location.hostname.endsWith('.invalid')) throw new Error('Reserved fixture origin required');
const documentID = crypto.randomUUID();
const generation = () => (window as unknown as { __cognisNative?: { generation?: string } }).__cognisNative?.generation;
function trace(event: string, detail: unknown = null) {
  const record = { documentID, ms: performance.now(), event, detail };
  console.log('DOCUMENT_TRACE', JSON.stringify(record));
  (window as unknown as { webkit?: { messageHandlers?: { documentTrace?: { postMessage(value: unknown): void } } } })
    .webkit?.messageHandlers?.documentTrace?.postMessage(JSON.stringify(record));
}
function scopeState(value: unknown) {
  const state = value as { epoch?: string; account?: unknown; blocked?: boolean; refresh?: string } | null;
  return state && { epoch: state.epoch, accountPresent: !!state.account, blocked: state.blocked, refresh: state.refresh };
}
const setStorage = Storage.prototype.setItem;
Storage.prototype.setItem = function (key, value) {
  if (key.startsWith('cognis-document-scope:')) trace('scope.write', {
    state: scopeState(JSON.parse(value)), stack: new Error().stack?.split('\n').slice(1, 6),
  });
  return setStorage.call(this, key, value);
};
for (const method of ['verified', 'invalidate', 'dispose', 'run'] as const) {
  const original = DocumentCoordination.prototype[method] as (...args: unknown[]) => unknown;
  Object.assign(DocumentCoordination.prototype, { [method]: function (this: DocumentCoordination, ...args: unknown[]) {
    trace(`owner.${method}`, { scope: scopeState((this as unknown as { current: unknown }).current),
      operation: method === 'run' ? String(args[0]).split(':')[0] : undefined,
      generation: generation() });
    return original.apply(this, args);
  } });
}
window.addEventListener('storage', (event) => {
  if (event.key?.startsWith('cognis-document-scope:')) trace('scope.storage-event', {
    before: scopeState(event.oldValue ? JSON.parse(event.oldValue) : null),
    after: scopeState(event.newValue ? JSON.parse(event.newValue) : null),
  });
});
window.addEventListener('pagehide', () => trace('pagehide'));
window.addEventListener('pageshow', () => trace('pageshow'));
trace('fixture.initialize', { origin: location.origin, generation: generation() });
const gates = new Map<string, { promise: Promise<void>; resolve: () => void }>();
const pending = new Map<string, Promise<unknown>>();
const calls = { refresh: 0, send: 0, upload: 0, logout: 0 };
let failNextSend = false;
let email = 'first@coordination.invalid';
let outbox: ChatV2Outbox;
let drafts = new DocumentDrafts();
const owner = documentCoordination();
owner.onInvalidated(() => trace('owner.invalidated', {
  current: scopeState((owner as unknown as { current: unknown }).current),
  generation: generation(),
}));
auth.subscribe((state) => trace('auth.state', { status: state.status, initialized: state.initialized }));
const settle = (kind: string, operation: Promise<unknown>) => {
  pending.set(kind, operation.then((value) => {
    trace(`operation.${kind}.completed`, { value: typeof value === 'boolean' ? value : undefined });
    return 'completed';
  }, (error) => {
    trace(`operation.${kind}.rejected`, { name: error?.name, message: error?.message, stack: error?.stack });
    return 'rejected';
  }));
  return true;
};
const wait = async (kind: string) => { await gates.get(kind)?.promise; };
const json = (data: unknown) => new Response(JSON.stringify(data), {
  status: 200, headers: { 'Content-Type': 'application/json' },
});
// All transport is controlled in this fixture; no request reaches the network.
globalThis.fetch = async (input) => {
  const url = String(input);
  trace('transport', { endpoint: url.split('/').pop() });
  if (url.endsWith('/refresh')) { calls.refresh++; await wait('refresh'); }
  if (url.endsWith('/logout')) calls.logout++;
  return url.endsWith('/me') ? json({ email, name: 'Fixture', role: 'user' })
    : json({ status: 'authenticated', user: { email, name: 'Fixture', role: 'user' }, expires_at: '2030-01-01T00:00:00Z' });
};
const send = async (_conversation: string, txn: string): Promise<SendMessageV2Response> => {
  calls.send++; await wait('send');
  if (failNextSend) { failNextSend = false; throw new Error('offline fixture'); }
  return { status: 'accepted', conversation_id: 'fixture-conversation', client_txn_id: txn,
    client_message_id: txn, server_time: '2026-01-01T00:00:00Z' };
};
const uploads = new AttachmentUploadManager(undefined, async () => {
  calls.upload++; await wait('upload');
  return { artifact_id: 'fixture-artifact', filename: 'fixture.txt', mime_type: 'text/plain',
    kind: 'file', size_bytes: 4, url: null };
}, undefined, () => {
  const lease = owner.capture();
  return { coordination: owner, lease, blobs: new AttachmentBlobStore(undefined,
    owner.storageName(ATTACHMENT_UPLOADS_DB_NAME, lease), lease) };
});
let local: AttachmentRef;

Object.assign(window, { documentFixture: {
  async shutdown() {
    trace('fixture.shutdown.start');
    for (const gate of gates.values()) gate.resolve();
    await Promise.allSettled(pending.values());
    uploads.reset();
    owner.dispose();
    trace('fixture.shutdown.finish');
    return true;
  },
  async bootstrap() {
    await auth.bootstrap();
    outbox = createIndexedDbChatV2Outbox();
    return auth.getSnapshot().status;
  },
  hold(kind: string) {
    let resolve!: () => void;
    const promise = new Promise<void>((done) => { resolve = done; });
    gates.set(kind, { promise, resolve });
    return true;
  },
  release(kind: string) { gates.get(kind)?.resolve(); return true; },
  refresh() { return settle('refresh', auth.refreshSession()); },
  async enqueue(txn: string) {
    await outbox.put({ client_txn_id: txn, client_message_id: txn,
      conversation_id: 'fixture-conversation', content: 'isolated fixture', attachments: [],
      status: 'pending', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' });
    return true;
  },
  async send(txn: string) {
    return settle('send', sendOutboxEntry(outbox, (await outbox.get(txn))!, send));
  },
  drain() { return settle('drain', drainConversationOutbox({ outbox, conversationId: 'fixture-conversation',
    sendMessage: send, isCurrent: () => true, onAdmitted: () => {} })); },
  receipt(txn: string) { return outbox.get(txn).then((entry) => entry?.status ?? 'missing'); },
  failNextSend() { failNextSend = true; return true; },
  async delayedFailure(txn: string) {
    const entry = (await outbox.get(txn))!;
    await outbox.update(txn, { status: 'failed', retryable: true });
    let failedEffects = 0;
    const outcome = await projectAdmissionFailure(outbox, entry,
      () => { failedEffects++; }, () => {});
    return { outcome, failedEffects, state: (await outbox.get(txn))?.status };
  },
  readDraft() { return drafts.read('cognis-draft:fixture'); },
  writeDraft(value: string) { return drafts.write('cognis-draft:fixture', value).then(() => true); },
  clearDraft(value: string) { return drafts.removeIfValue('cognis-draft:fixture', value).then(() => true); },
  stage() { local = uploads.stage(new File(['data'], 'fixture.txt', { type: 'text/plain' })); return local; },
  resolveAttachment(ref: AttachmentRef) { return settle('upload', uploads.resolve(ref)); },
  prune() { return uploads.prune([]).then(() => true); },
  wait(kind: string) { return pending.get(kind) ?? Promise.resolve('not-started'); },
  logout() { return auth.logout().then(() => true); },
  async loginSecond() {
    email = 'second@coordination.invalid';
    await auth.login(email, 'fixture-not-a-credential');
    outbox = createIndexedDbChatV2Outbox();
    drafts = new DocumentDrafts();
    return auth.getSnapshot().status;
  },
  async legacyNotice() {
    localStorage.setItem('cognis-draft:fixture', 'unknown-owner-fixture');
    await inspectRetainedData();
    return localStorage.getItem('cognis-draft:fixture') === 'unknown-owner-fixture';
  },
  status() { return { ...calls, auth: auth.getSnapshot().status, owner: owner.owner,
    error: auth.getSnapshot().error,
    scope: Object.fromEntries(Object.keys(localStorage)
      .filter((key) => key.startsWith('cognis-document-scope:'))
      .map((key) => [key, localStorage.getItem(key)])) }; },
} });
