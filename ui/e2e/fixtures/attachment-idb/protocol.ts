import { documentCoordination } from '../../../src/lib/document-coordination';
import { DocumentDrafts } from '../../../src/lib/offline/document-drafts';
import { ComposerSubmission, type ComposerView } from '../../../src/lib/chat-v2/composer-submission';
import { normalizeChatComposerInput } from '../../../src/lib/chat-v2/composer-dispatch';
import { normalizeSubmissionInput } from '../../../src/lib/chat-v2/submission-input';
import { CoordinatedOutbox, IndexedDbChatV2Outbox, type OutboxEntry } from '../../../src/lib/chat-v2/outbox';
import { sendOutboxEntry, drainConversationOutbox } from '../../../src/lib/chat-v2/outbox-send';
import { AttachmentBlobStore, ATTACHMENT_UPLOADS_DB_NAME } from '../../../src/lib/chat-v2/attachment-blobs';
import { AttachmentUploadManager } from '../../../src/lib/chat-v2/attachment-uploads';
import type { AttachmentRef } from '../../../src/lib/types/api';
import { phase, observed } from './diagnostics';

phase('protocol:module-boot');

interface Manifest { namespace: string; view: ComposerView; txn?: string; message?: string; failedTxn?: string }
async function owners(namespace: string) {
  const coordination = documentCoordination();
  await observed('owner:initialize', () => coordination.initialize());
  await observed('owner:verified', () => coordination.verified('synthetic-native@cognis.test'));
  const lease = coordination.capture();
  const drafts = new DocumentDrafts();
  const outbox = new CoordinatedOutbox(
    new IndexedDbChatV2Outbox(indexedDB, `${namespace}-protocol`, lease), coordination);
  const blobs = new AttachmentBlobStore(() => indexedDB, coordination.storageName(ATTACHMENT_UPLOADS_DB_NAME, lease), lease);
  // Transport is deliberately synthetic. Protocol/storage owners are production.
  const uploads = new AttachmentUploadManager(blobs, async () => { throw new Error('Unexpected second upload'); });
  return { coordination, lease, drafts, outbox, blobs, uploads };
}
function proposal(view: ComposerView): OutboxEntry {
  const normalized = normalizeChatComposerInput({ content: view.text, chatMode: view.chat_mode ?? undefined });
  if (normalized.kind !== 'message') throw new Error('Unexpected synthetic command');
  return {
    client_txn_id: crypto.randomUUID(), client_message_id: crypto.randomUUID(),
    conversation_id: view.conversationId, content: normalized.content,
    attachments: view.attachments, chat_mode: normalized.chatMode ?? null,
    status: 'pending', created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  };
}
function binding(view: ComposerView) {
  if (!view.draftKey) throw new Error('Synthetic input requires a draft key');
  return { version: 1 as const, draft_key: view.draftKey,
    input_revision: view.input_revision, input: normalizeSubmissionInput(view) };
}
async function peer(manifest: Manifest, operation: 'reserve' | 'activate') {
  const owner = await observed('peer:owners', () => owners(manifest.namespace));
  return observed(`peer:${operation}`, () => operation === 'reserve'
    ? owner.outbox.reserve(proposal(manifest.view), binding(manifest.view))
    : owner.outbox.activate(manifest.txn!, manifest.view.attachments));
}
// Fixture-only interface on a genuine second document, not an app-private seam.
declare global {
  interface Window { attachmentProtocolPeer: typeof peer }
}
window.attachmentProtocolPeer = peer;
phase('peer:handler-ready');

export async function runProtocol(namespace: string, files: File[]) {
  const owner = await observed('protocol:owners', () => owners(namespace));
  let finishUpload!: (ref: AttachmentRef) => void;
  let uploadCount = 0;
  const uploadResult = new Promise<AttachmentRef>((resolve) => { finishUpload = resolve; });
  const uploads = new AttachmentUploadManager(owner.blobs, async () => { uploadCount++; return uploadResult; });
  phase('protocol:stage:start');
  const staged = uploads.stage(files[0]);
  phase('protocol:stage:returned');
  let view: ComposerView = {
    conversationId: namespace, generation: 1, draftKey: `cognis-chat-draft:${namespace}`,
    revision: 1, input_revision: crypto.randomUUID(), chat_mode: 'default',
    text: 'Synthetic protocol input', attachments: [staged],
  };
  await observed('protocol:stage-durability', () => uploads.prepare(view.attachments, owner.lease));
  const frame = document.createElement('iframe');
  frame.src = `${location.pathname}?synthetic-peer=1`;
  const loaded = new Promise<void>((resolve, reject) => {
    frame.onload = () => resolve(); frame.onerror = () => reject(new Error('Peer failed to load'));
  });
  document.body.append(frame);
  await observed('protocol:peer-load', () => loaded);
  try {
    const manifest: Manifest = { namespace, view };
    const [a, b] = await observed('protocol:reserve-race', () => Promise.all([
      observed('protocol:reserve-main', () => owner.outbox.reserve(proposal(view), binding(view))),
      observed('protocol:reserve-peer', () => frame.contentWindow!.attachmentProtocolPeer(manifest, 'reserve')),
    ]));
    const sameReservation = a.client_txn_id === b.client_txn_id && a.client_message_id === b.client_message_id;
    let sends = 0;
    const transport = async (conversation: string, txn: string, request: { client_message_id: string }) => {
      sends++;
      return { status: 'accepted' as const, conversation_id: conversation, client_txn_id: txn,
        client_message_id: request.client_message_id, server_time: new Date().toISOString() };
    };
    const directBlocked = await observed('protocol:preparing-direct', () => sendOutboxEntry(owner.outbox, a, transport).then(() => false, () => true));
    await observed('protocol:preparing-drain', () => drainConversationOutbox({ outbox: owner.outbox, conversationId: namespace,
      sendMessage: transport, isCurrent: () => true, onAdmitted: () => {} }));
    const preparingNotDrained = sends === 0;
    const [activated, peerActivated] = await observed('protocol:activate-race', () => Promise.all([
      observed('protocol:activate-main', () => owner.outbox.activate(a.client_txn_id, view.attachments)),
      observed('protocol:activate-peer', () => frame.contentWindow!.attachmentProtocolPeer({ ...manifest, txn: a.client_txn_id }, 'activate')),
    ]));
    const sameActivation = JSON.stringify(activated) === JSON.stringify(peerActivated);
    const submission = new ComposerSubmission(view, proposal(view), owner.lease, uploads);
    const canonical = await observed('protocol:submission-prepare', () => submission.prepare(owner.drafts, owner.outbox));
    const retry = await observed('protocol:submission-retry', () => new ComposerSubmission(view, proposal(view), owner.lease, uploads)
      .prepare(new DocumentDrafts(), owner.outbox));
    finishUpload({ artifact_id: `synthetic-artifact-${crypto.randomUUID()}`, filename: files[0].name,
      mime_type: files[0].type, kind: 'image', size_bytes: files[0].size });
    await observed('protocol:upload-receipt', () => uploads.resolve(staged)); // Synthetic transport only.
    const resolved = await observed('protocol:upload-reopen', () => owner.uploads.resolve(staged));
    const receiptStored = (await observed('protocol:receipt-read', () => owner.blobs.get(staged.local_id!)))?.result?.artifact_id === resolved.artifact_id;
    await observed('protocol:send', () => sendOutboxEntry(owner.outbox, canonical, transport));
    await observed('protocol:send-retry', () => sendOutboxEntry(owner.outbox, retry, transport));
    const accepted = await observed('protocol:accepted-read', () => owner.outbox.get(canonical.client_txn_id));
    const reserveAgain = await observed('protocol:accepted-reserve', () => owner.outbox.reserve(proposal(view), binding(view)));
    const receiptUnchanged = JSON.stringify(accepted) === JSON.stringify(reserveAgain);
    sessionStorage.setItem('synthetic-protocol-reload', JSON.stringify({
      namespace, view, txn: canonical.client_txn_id, message: canonical.client_message_id,
    } satisfies Manifest));
    // Save the pre-consumption view in the manifest, then consume through the real owner.
    const consumed = await observed('protocol:consume', () => submission.consume(owner.drafts, () => view, () => {
      view = { ...view, text: '', attachments: [], revision: view.revision + 1 };
    }));
    const failedStore = new AttachmentBlobStore(() => undefined);
    const failedUploads = new AttachmentUploadManager(failedStore, async () => { throw new Error('Must not upload'); });
    phase('protocol:failed-stage:start');
    const failedRef = failedUploads.stage(files[1]);
    phase('protocol:failed-stage:returned');
    const failedView = { ...view, input_revision: crypto.randomUUID(), text: 'Synthetic failed staging',
      attachments: [failedRef], revision: view.revision + 1 };
    const failed = new ComposerSubmission(failedView, proposal(failedView), owner.lease, failedUploads);
    const stagingRejected = await observed('protocol:failed-prepare', () => failed.prepare(owner.drafts, owner.outbox).then(() => false, () => true));
    let cleared = false;
    await observed('protocol:failed-consume', () => failed.consume(owner.drafts, () => failedView, () => { cleared = true; }));
    const failedRow = (await observed('protocol:failed-row', () => owner.outbox.list(namespace))).find(row => row.submission?.input_revision === failedView.input_revision);
    const stagingRetained = stagingRejected && !cleared && failedRow?.status === 'preparing';
    const staleView = { ...failedView, input_revision: crypto.randomUUID(), attachments: [], revision: failedView.revision + 1 };
    const stale = new ComposerSubmission(staleView, proposal(staleView), owner.lease, owner.uploads);
    await observed('protocol:stale-prepare', () => stale.prepare(owner.drafts, owner.outbox));
    const staleRetained = !await observed('protocol:stale-consume', () => stale.consume(owner.drafts, () => ({ ...staleView, generation: 2 }), () => { cleared = true; }));
    const modeRows = await observed('protocol:modes', () => Promise.all(([null, 'default', 'plan', 'build'] as const).map(async (mode) => {
      const intent = { ...staleView, input_revision: crypto.randomUUID(), chat_mode: mode };
      const row = await observed(`protocol:mode-${mode ?? 'inherit'}`, () => owner.outbox.reserve(proposal(intent), binding(intent)));
      return row.submission?.input.chat_mode === mode && row.chat_mode === mode;
    })));
    await observed('protocol:invalidate', () => owner.coordination.invalidate(false));
    const revoked = await observed('protocol:revoked-read', () => owner.outbox.get(canonical.client_txn_id).then(() => false, () => true));
    return { sameReservation, sameActivation, directBlocked, preparingNotDrained, consumed,
      sameRetry: canonical.client_txn_id === retry.client_txn_id && canonical.client_message_id === retry.client_message_id,
      receiptStored, receiptUnchanged, stagingRetained, staleRetained, revoked,
      oneSend: sends === 1, oneUpload: uploadCount === 1, modeSemantics: modeRows.every(Boolean) };
  } finally { frame.remove(); }
}

export async function reloadProtocol() {
  const manifest = JSON.parse(sessionStorage.getItem('synthetic-protocol-reload')!) as Manifest;
  const owner = await observed('protocol-reload:owners', () => owners(manifest.namespace));
  const row = await observed('protocol-reload:get', () => owner.outbox.get(manifest.txn!));
  const same = await observed('protocol-reload:reserve', () => owner.outbox.reserve(proposal(manifest.view), binding(manifest.view)));
  const receipt = await observed('protocol-reload:receipt', () => owner.blobs.get(manifest.view.attachments[0].local_id!));
  return {
    reloadBinding: same.client_txn_id === manifest.txn && same.client_message_id === manifest.message,
    reloadReceipt: row?.status === 'acked' && !!row.admitted && JSON.stringify(same) === JSON.stringify(row),
    reloadUploadReceipt: !!receipt?.result,
  };
}
