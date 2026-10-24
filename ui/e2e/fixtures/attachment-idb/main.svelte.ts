/// <reference types="svelte" />
import { IndexedDbChatV2Outbox, type OutboxEntry } from '../../../src/lib/chat-v2/outbox';
import { AttachmentBlobStore } from '../../../src/lib/chat-v2/attachment-blobs';
import type { DocumentLease } from '../../../src/lib/document-coordination';
import { runProtocol, reloadProtocol } from './protocol';
import { phase, observed, errorName } from './diagnostics';

phase('main:module-boot');

const errors: string[] = [];
const warnings: string[] = [];
const warn = console.warn.bind(console);
console.warn = (...args: unknown[]) => { warnings.push('Warning'); warn(...args); };
window.addEventListener('error', (event) => { errors.push(errorName(event.error)); });
const namespace = `synthetic-attachment-diagnostic-${crypto.randomUUID()}`;
const controller = new AbortController();
const assertCurrent = () => controller.signal.throwIfAborted();
const lease: DocumentLease = { owner: namespace, epoch: namespace,
  signal: controller.signal, assertCurrent, async validate() { assertCurrent(); } };

async function image(mime: string): Promise<File> {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 2;
  canvas.getContext('2d')!.fillRect(0, 0, 2, 2);
  const blob = await observed(`encode:${mime}`, () => new Promise<Blob>((resolve, reject) => canvas.toBlob(
    (value) => value ? resolve(value) : reject(new Error('Synthetic image encoding failed')), mime)));
  return new File([blob], mime === 'image/png' ? 'synthetic.png' : 'synthetic.jpg', { type: mime });
}

async function baseline(entry: OutboxEntry): Promise<{ name: string; message: string }> {
  const db = await observed('legacy-clone:open', () => new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(`${namespace}-baseline`, 1);
    request.onupgradeneeded = () => request.result.createObjectStore('outbox', { keyPath: 'client_txn_id' });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  }));
  try {
    return await observed('legacy-clone:transaction', () => new Promise<{ name: string; message: string }>((resolve, reject) => {
      const tx = db.transaction('outbox', 'readwrite'), store = tx.objectStore('outbox');
      tx.oncomplete = () => reject(new Error('Proxy baseline unexpectedly committed'));
      tx.onabort = () => resolve({ name: tx.error?.name ?? '', message: tx.error?.message ?? '' });
      // Intentional negative control matching the original outbox callback.
      store.get(entry.client_txn_id).onsuccess = () => { phase('legacy-clone:callback'); store.put(entry); };
    }));
  } finally { db.close(); }
}

async function run() {
  const files = await observed('images', () => Promise.all(['image/png', 'image/jpeg'].map(image)));
  const attachments = $state(files.map((file) => ({
    artifact_id: `local:${file.name}`, local_id: file.name, filename: file.name,
    mime_type: file.type, kind: 'image', size_bytes: file.size,
  })));
  const entry: OutboxEntry = {
    client_txn_id: crypto.randomUUID(), client_message_id: crypto.randomUUID(),
    conversation_id: namespace, content: 'Synthetic images only', attachments: [...attachments],
    status: 'pending', created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  };
  const negative = await observed('legacy-clone', () => baseline(entry));
  const outbox = new IndexedDbChatV2Outbox(indexedDB, `${namespace}-outbox`, lease);
  const blobs = new AttachmentBlobStore(() => indexedDB, `${namespace}-bytes`, lease);
  const bytes: Array<{ kind: string; mime: string; committed: boolean; equal: boolean }> = [];
  const byteChecks: Array<{ id: string; bytes: number[] }> = [];
  for (const file of files) {
    for (const kind of ['File', 'Blob'] as const) {
      const id = `${kind}:${file.name}`, blob = kind === 'File' ? file : new Blob([file], { type: file.type });
      const label = `bytes:${kind}:${file.type}`;
      const committed = await observed(`${label}:put`, () => blobs.put({ local_id: id, blob, filename: file.name, mime_type: file.type, created_at: Date.now() }));
      const reopened = new AttachmentBlobStore(() => indexedDB, `${namespace}-bytes`, lease);
      const read = await observed(`${label}:reopen`, () => reopened.get(id));
      const actual = read?.blob ? new Uint8Array(await observed(`${label}:actual`, () => read.blob!.arrayBuffer())) : null;
      const expected = new Uint8Array(await observed(`${label}:expected`, () => file.arrayBuffer()));
      byteChecks.push({ id, bytes: Array.from(expected) });
      bytes.push({ kind, mime: file.type, committed,
        equal: actual !== null && actual.length === expected.length && actual.every((byte, i) => byte === expected[i]) });
    }
  }
  await observed('metadata:put', () => outbox.put(entry));
  await observed('metadata:update', () => outbox.update(entry.client_txn_id, { attachments: [...attachments] }));
  const saved = await observed('metadata:reopen', () => new IndexedDbChatV2Outbox(indexedDB, `${namespace}-outbox`, lease).get(entry.client_txn_id));
  await observed('metadata:duplicate-put', () => outbox.put(entry));
  const duplicateRows = (await observed('metadata:list', () => outbox.list(namespace))).length;
  (window as unknown as { partial: unknown }).partial = { negative, errors, warnings, bytes,
    metadata: saved?.attachments.length === 2, duplicateRows };
  sessionStorage.setItem('synthetic-reload', JSON.stringify({ namespace, txn: entry.client_txn_id, byteChecks }));
  const protocol = await observed('protocol', () => runProtocol(namespace, files));
  controller.abort(new Error('Synthetic owner revocation'));
  const revoked = await observed('metadata:revoked', () => outbox.put({ ...entry, client_txn_id: crypto.randomUUID() }).then(() => false, () => true));
  return { userAgent: navigator.userAgent, negative, errors, bytes,
    metadata: saved?.attachments.length === 2 && saved.client_message_id === entry.client_message_id, revoked,
    duplicateRows, protocol };
}

(window as unknown as { verifyReload: () => void }).verifyReload = () => {
  phase('reload:invoked');
  void (async () => {
    const saved = JSON.parse(sessionStorage.getItem('synthetic-reload')!);
    const outbox = new IndexedDbChatV2Outbox(indexedDB, `${saved.namespace}-outbox`, lease);
    const blobs = new AttachmentBlobStore(() => indexedDB, `${saved.namespace}-bytes`, lease);
    const row = await observed('reload:metadata', () => outbox.get(saved.txn));
    const png = await observed('reload:png', () => blobs.get('File:synthetic.png'));
    const jpeg = await observed('reload:jpeg', () => blobs.get('File:synthetic.jpg'));
    const checks = await observed('reload:all-bytes', () => Promise.all((saved.byteChecks as Array<{ id: string; bytes: number[] }>).map(async (check, index) => {
      const stored = await observed(`reload:case-${index}:get`, () => blobs.get(check.id));
      const bytes = stored?.blob ? new Uint8Array(await observed(`reload:case-${index}:bytes`, () => stored.blob!.arrayBuffer())) : null;
      return bytes !== null && bytes.length === check.bytes.length && bytes.every((value, index) => value === check.bytes[index]);
    })));
    document.getElementById('result')!.textContent = JSON.stringify({
      ...await observed('reload:protocol', reloadProtocol), reloadMetadata: row?.attachments.length === 2,
      reloadAllFourBytes: checks.length === 4 && checks.every(Boolean),
      reloadPNG: (png?.blob?.size ?? 0) > 0, reloadJPEG: (jpeg?.blob?.size ?? 0) > 0,
    });
    phase('reload:result-published');
  })().catch((error) => { phase(`reload:failed:${errorName(error)}`); document.getElementById('result')!.textContent = JSON.stringify({ failure: errorName(error) }); });
};

document.getElementById('run')!.onclick = async () => {
  phase('run:invoked');
  const output = document.getElementById('result')!;
  output.textContent = 'Running';
  try { output.textContent = JSON.stringify(await run(), null, 2); phase('run:result-published'); }
  catch (error) { phase(`run:failed:${errorName(error)}`); output.textContent = JSON.stringify({ failure: errorName(error), errors,
    partial: (window as unknown as { partial: unknown }).partial }); }
};
phase('main:handlers-ready');
