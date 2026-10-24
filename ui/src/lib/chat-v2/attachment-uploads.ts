// Background attachment uploads for the chat composer.
//
// Picking a file shows it in the composer immediately and starts uploading
// in the background with progress. Sending does not wait: the message goes
// into the outbox with local attachment placeholders, and the outbox resolves
// them (awaiting the in-flight upload, or re-uploading from the durable blob
// copy after a reload) right before the message is admitted.

import { apiUrl } from '$lib/config';
import { auth } from '$lib/stores/auth';
import { api } from '$lib/api/client';
import { snapshotPersistedMetadata } from './persisted-metadata';
import type { AttachmentRef } from '$lib/types/api';
import { AttachmentBlobStore, ATTACHMENT_UPLOADS_DB_NAME } from './attachment-blobs';
import { documentCoordination, type DocumentLease, type DocumentCoordination } from '$lib/document-coordination';

export const LOCAL_ATTACHMENT_PREFIX = 'local:';

export class AttachmentUploadError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, { status, code }: { status: number; code?: string }) {
    super(message);
    this.name = 'AttachmentUploadError';
    this.status = status;
    this.code = code ?? (status === 0 ? 'network_error' : 'upload_failed');
  }
}

export function isLocalAttachment(ref: AttachmentRef): boolean {
  return Boolean(ref.local_id) || ref.artifact_id.startsWith(LOCAL_ATTACHMENT_PREFIX);
}

/** Server payload shape: drop client-only tracking and local preview URLs. */
export function toServerAttachment(ref: AttachmentRef): AttachmentRef {
  const {
    local_id: _localId,
    upload_state: _state,
    upload_progress: _progress,
    upload_error: _error,
    blob_url: _blobUrl,
    ...rest
  } = ref;
  return rest;
}

export function attachmentKindForMime(mime: string): string {
  if (mime.startsWith('image/')) return 'image';
  if (mime.startsWith('audio/')) return 'audio';
  if (mime.startsWith('video/')) return 'video';
  if (mime === 'application/pdf') return 'pdf';
  return 'file';
}

function parseErrorMessage(body: string, status: number): string {
  try {
    const payload = JSON.parse(body) as {
      error?: { message?: string };
      detail?: string | { message?: string };
    };
    if (payload?.error?.message) return payload.error.message;
    if (typeof payload?.detail === 'string') return payload.detail;
    if (payload?.detail && typeof payload.detail === 'object' && payload.detail.message) {
      return payload.detail.message;
    }
  } catch {
    // Non-JSON error body.
  }
  return status === 413 ? 'The file is too large.' : `Upload failed (${status}).`;
}

export type UploadTransport = (
  blob: Blob,
  filename: string,
  options: { onProgress: (fraction: number) => void; signal: AbortSignal },
) => Promise<AttachmentRef>;

/**
 * Abort an upload that makes no progress for this long. A total timeout would
 * kill legitimate large uploads on slow links; a stall means a dead socket.
 */
export const UPLOAD_STALL_TIMEOUT_MS = 60_000;

/** XHR upload (fetch has no upload progress). One retry after a 401 refresh. */
export const xhrUploadTransport: UploadTransport = async (blob, filename, options) => {
  const attempt = (): Promise<{ status: number; body: string }> => new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    let stalled = false;
    let stallTimer: ReturnType<typeof setTimeout> | null = null;
    const armStallTimer = () => {
      if (stallTimer !== null) clearTimeout(stallTimer);
      stallTimer = setTimeout(() => {
        stalled = true;
        xhr.abort();
      }, UPLOAD_STALL_TIMEOUT_MS);
    };
    const settle = () => {
      if (stallTimer !== null) clearTimeout(stallTimer);
      stallTimer = null;
      options.signal.removeEventListener('abort', abort);
    };
    xhr.open('POST', apiUrl('/api/v1/artifacts/upload'));
    xhr.withCredentials = true;
    xhr.responseType = 'text';
    xhr.upload.onprogress = (event) => {
      armStallTimer();
      if (event.lengthComputable && event.total > 0) options.onProgress(event.loaded / event.total);
    };
    xhr.onprogress = armStallTimer;
    xhr.onload = () => {
      settle();
      resolve({ status: xhr.status, body: xhr.responseText ?? '' });
    };
    xhr.onerror = () => {
      settle();
      reject(new AttachmentUploadError('Network error while uploading.', { status: 0 }));
    };
    xhr.onabort = () => {
      settle();
      reject(stalled
        ? new AttachmentUploadError('Upload stalled. It will be retried.', { status: 0, code: 'request_timeout' })
        : new DOMException('Upload cancelled', 'AbortError'));
    };
    const abort = () => xhr.abort();
    if (options.signal.aborted) {
      reject(new DOMException('Upload cancelled', 'AbortError'));
      return;
    }
    options.signal.addEventListener('abort', abort, { once: true });
    armStallTimer();
    const form = new FormData();
    form.set('file', blob, filename);
    form.set('purpose', 'chat_input');
    xhr.send(form);
  });

  let result = await attempt();
  if (result.status === 401 && (await auth.recoverSession()) === 'valid') {
    result = await attempt();
  }
  if (result.status < 200 || result.status >= 300) {
    throw new AttachmentUploadError(parseErrorMessage(result.body, result.status), { status: result.status });
  }
  return JSON.parse(result.body) as AttachmentRef;
};

interface UploadRecord {
  scope?: UploadScope;
  ref: AttachmentRef;
  file: Blob | null;
  durable: boolean;
  durablePromise: Promise<boolean>;
  promise: Promise<AttachmentRef> | null;
  controller: AbortController | null;
  result: AttachmentRef | null;
}

export type UploadChangeListener = (localId: string, patch: Partial<AttachmentRef>) => void;
interface UploadScope { lease: DocumentLease; coordination: DocumentCoordination; blobs: AttachmentBlobStore }

export class AttachmentUploadManager {
  private readonly records = new Map<string, UploadRecord>();
  private readonly listeners = new Set<UploadChangeListener>();
  private activeScope?: UploadScope;

  constructor(
    private readonly blobs: AttachmentBlobStore = new AttachmentBlobStore(),
    private readonly transport: UploadTransport = xhrUploadTransport,
    private readonly uuid: () => string = () => crypto.randomUUID(),
    private readonly scopeFactory?: () => UploadScope,
    private readonly verifyArtifact = (id: string) => api.artifacts.signedUrl(encodeURIComponent(id)),
  ) {}

  private scope(): UploadScope | undefined {
    if (!this.scopeFactory) return undefined;
    if (!this.activeScope || this.activeScope.lease.signal.aborted) {
      this.reset();
      this.activeScope = this.scopeFactory();
    }
    this.activeScope.lease.assertCurrent();
    return this.activeScope;
  }

  onChange(listener: UploadChangeListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Current upload state of a staged attachment, for views (such as a sent
   * message bubble) that hold an older copy of the attachment reference.
   * Null when this page does not track the attachment.
   */
  uploadState(localId: string): Pick<AttachmentRef, 'upload_state' | 'upload_progress' | 'upload_error'> | null {
    const record = this.records.get(localId);
    if (!record) return null;
    if (record.result) return { upload_state: 'uploaded', upload_progress: 1, upload_error: null };
    const { upload_state, upload_progress, upload_error } = record.ref;
    return { upload_state, upload_progress, upload_error };
  }

  /** Create a local placeholder for `file` and start uploading it. */
  stage(file: File): AttachmentRef {
    const scope = this.scope();
    const localId = this.uuid();
    const mime = file.type || 'application/octet-stream';
    const previewUrl = mime.startsWith('image/') && typeof URL !== 'undefined' && URL.createObjectURL
      ? URL.createObjectURL(file)
      : null;
    const ref: AttachmentRef = {
      artifact_id: `${LOCAL_ATTACHMENT_PREFIX}${localId}`,
      kind: attachmentKindForMime(mime),
      mime_type: mime,
      filename: file.name || 'attachment',
      size_bytes: file.size,
      url: previewUrl,
      blob_url: previewUrl,
      local_id: localId,
      upload_state: 'uploading',
      upload_progress: 0,
      upload_error: null,
    };
    const durablePromise = (scope?.blobs ?? this.blobs).put({
      local_id: localId,
      blob: file,
      filename: ref.filename,
      mime_type: mime,
      created_at: Date.now(),
    });
    const record: UploadRecord = {
      scope,
      ref,
      file,
      durable: false,
      durablePromise,
      promise: null,
      controller: null,
      result: null,
    };
    void durablePromise.then((durable) => { record.durable = durable; }).catch(() => undefined);
    this.records.set(localId, record);
    void this.start(localId).catch(() => undefined);
    return ref;
  }

  /** True when the file bytes survive a reload until the upload finishes. */
  async isDurable(ref: AttachmentRef): Promise<boolean> {
    const scope = this.scope();
    const blobs = scope?.blobs ?? this.blobs;
    const localId = ref.local_id ?? (isLocalAttachment(ref)
      ? ref.artifact_id.slice(LOCAL_ATTACHMENT_PREFIX.length) : null);
    if (localId) {
      await this.records.get(localId)?.durablePromise;
      const stored = await blobs.get(localId);
      if (scope) await scope.lease.validate();
      return Boolean(stored?.blob || stored?.result);
    }
    const stored = await blobs.get(`server:${ref.artifact_id}`);
    if (scope) await scope.lease.validate();
    return stored?.result?.artifact_id === ref.artifact_id;
  }

  /** Pin durable bytes or authenticated server availability before consumption. */
  async prepare(refs: AttachmentRef[], lease: DocumentLease): Promise<void> {
    const scope = this.scope();
    await lease.validate();
    if (scope && (scope.lease.owner !== lease.owner || scope.lease.epoch !== lease.epoch)) {
      throw new Error('Attachment owner changed');
    }
    const blobs = scope?.blobs ?? this.blobs;
    for (const ref of snapshotPersistedMetadata(refs)) {
      if (await this.isDurable(ref)) { await lease.validate(); continue; }
      await lease.validate();
      if (isLocalAttachment(ref)) throw new AttachmentUploadError('Attachment storage is unavailable. Input retained.',
        { status: 0, code: 'upload_storage_unavailable' });
      // Library/already-uploaded attachments need no local bytes. Authenticate
      // availability instead of trusting an artifact id supplied by the view.
      const verified = await this.verifyArtifact(ref.artifact_id);
      await lease.validate();
      if (verified.artifact_id !== ref.artifact_id) throw new Error('Attachment verification mismatch');
      const saved = await blobs.put({
        local_id: `server:${ref.artifact_id}`, blob: null, result: toServerAttachment(ref),
        filename: ref.filename, mime_type: ref.mime_type, created_at: Date.now(),
      });
      await lease.validate();
      if (!saved) throw new AttachmentUploadError('Attachment receipt could not be saved. Input retained.',
        { status: 0, code: 'upload_storage_unavailable' });
    }
  }

  /** Retry a failed upload now (e.g. user tapped retry on the chip). */
  retry(localId: string): void {
    void this.start(localId).catch(() => undefined);
  }

  /** Drop a staged attachment: abort its upload and forget the blob. */
  cancel(localId: string): void {
    const record = this.records.get(localId);
    record?.controller?.abort();
    if (record?.ref.blob_url) URL.revokeObjectURL(record.ref.blob_url);
    this.records.delete(localId);
    // Scoped files can be referenced by another document's draft/outbox.
    // Cancelling this view must not delete their bytes.
    if (!this.scopeFactory) void this.blobs.delete(localId);
  }

  /** Resolve a (possibly local) attachment to its uploaded server reference. */
  async resolve(ref: AttachmentRef): Promise<AttachmentRef> {
    const scope = this.scope();
    if (!isLocalAttachment(ref)) return toServerAttachment(ref);
    const localId = ref.local_id ?? ref.artifact_id.slice(LOCAL_ATTACHMENT_PREFIX.length);
    if (!this.records.has(localId)) {
      // After a reload: reuse the persisted upload result, or resume from
      // the durable blob copy.
      const stored = await (scope?.blobs ?? this.blobs).get(localId);
      if (scope) await scope.lease.validate();
      if (stored?.result) {
        const server = toServerAttachment(stored.result);
        this.records.set(localId, {
          scope,
          ref: { ...ref, local_id: localId },
          file: null,
          durable: true,
          durablePromise: Promise.resolve(true),
          promise: null,
          controller: null,
          result: server,
        });
        return server;
      }
      if (!stored?.blob) {
        throw new AttachmentUploadError(
          `Attachment "${ref.filename}" is no longer available. Attach it again.`,
          { status: 410, code: 'attachment_missing' },
        );
      }
      this.records.set(localId, {
        scope,
        ref: { ...ref, local_id: localId },
        file: stored.blob,
        durable: true,
        durablePromise: Promise.resolve(true),
        promise: null,
        controller: null,
        result: null,
      });
    }
    return this.start(localId);
  }

  async resolveAll(refs: AttachmentRef[]): Promise<AttachmentRef[]> {
    return Promise.all(refs.map((ref) => this.resolve(ref)));
  }

  /** Drop stored state for attachments of an admitted message. */
  forget(refs: AttachmentRef[]): void {
    for (const ref of refs) {
      const localId = ref.local_id
        ?? (ref.artifact_id.startsWith(LOCAL_ATTACHMENT_PREFIX)
          ? ref.artifact_id.slice(LOCAL_ATTACHMENT_PREFIX.length)
          : null);
      if (!localId) continue;
      const record = this.records.get(localId);
      if (record?.ref.blob_url) URL.revokeObjectURL(record.ref.blob_url);
      this.records.delete(localId);
      if (!this.scopeFactory) void this.blobs.delete(localId);
    }
  }

  /** Remove old stored files not referenced by any queued message. */
  async prune(queued: AttachmentRef[][]): Promise<void> {
    // Retain scoped bytes until reference-aware recovery/retention is approved.
    // Bounded per-file persistence still applies; never age-delete quarantined
    // bytes or infer that a sibling document has no live references.
    if (this.scopeFactory) return;
    const keep = new Set<string>();
    for (const refs of queued) {
      for (const ref of refs) {
        if (ref.local_id) keep.add(ref.local_id);
      }
    }
    for (const localId of this.records.keys()) keep.add(localId);
    await this.blobs.prune(keep);
  }

  /** Abort all uploads and forget in-memory state (logout/account switch). */
  reset(): void {
    for (const record of this.records.values()) {
      record.controller?.abort();
      if (record.ref.blob_url) URL.revokeObjectURL(record.ref.blob_url);
    }
    this.records.clear();
  }

  private start(localId: string): Promise<AttachmentRef> {
    this.scope();
    const record = this.records.get(localId);
    if (!record) {
      return Promise.reject(new AttachmentUploadError('Attachment was removed.', { status: 410, code: 'attachment_missing' }));
    }
    if (record.result) return Promise.resolve(record.result);
    if (record.promise) return record.promise;
    const file = record.file;
    if (!file) {
      return Promise.reject(new AttachmentUploadError('Attachment data is unavailable.', { status: 410, code: 'attachment_missing' }));
    }
    const controller = new AbortController();
    record.controller = controller;
    this.emit(localId, { upload_state: 'uploading', upload_error: null });
    let lastProgress = -1;
    const scope = record.scope;
    const execute = async () => {
      await record.durablePromise;
      if (scope) await scope.lease.validate();
      const blobs = scope?.blobs ?? this.blobs;
      // A sibling may have completed this upload while this document queued.
      const stored = scope ? await blobs.get(localId) : null;
      if (scope) await scope.lease.validate();
      if (stored?.result) return toServerAttachment(stored.result);
      if (scope) {
        if (!stored || stored.attempted) {
          throw new AttachmentUploadError('Upload outcome is uncertain. File retained for verified recovery.',
            { status: 409, code: 'upload_outcome_uncertain' });
        }
        const durable = await blobs.put({ ...stored, attempted: true });
        await scope.lease.validate();
        if (!durable) throw new AttachmentUploadError('Cannot durably coordinate this upload.',
          { status: 0, code: 'upload_storage_unavailable' });
      }
      const abort = () => controller.abort(scope?.lease.signal.reason);
      scope?.lease.signal.addEventListener('abort', abort, { once: true });
      try {
        const uploaded = await this.transport(file, record.ref.filename, {
      signal: controller.signal,
      onProgress: (fraction) => {
        if (scope?.lease.signal.aborted) return;
        const progress = Math.max(0, Math.min(1, fraction));
        // Throttle UI updates to whole percents.
        const percent = Math.floor(progress * 100);
        if (percent === lastProgress) return;
        lastProgress = percent;
        this.emit(localId, { upload_progress: progress });
      },
        });
        if (scope) await scope.lease.validate();
        const server = toServerAttachment(uploaded);
        const saved = await blobs.put({ local_id: localId, blob: null, result: server,
          filename: record.ref.filename, mime_type: record.ref.mime_type, created_at: Date.now() });
        if (scope) await scope.lease.validate();
        if (scope && !saved) throw new AttachmentUploadError('Upload receipt could not be saved. File retained for recovery.',
          { status: 409, code: 'upload_outcome_uncertain' });
        return server;
      } finally { scope?.lease.signal.removeEventListener('abort', abort); }
    };
    record.promise = (scope
      ? scope.coordination.run(`upload:${scope.lease.owner}:${localId}`, scope.lease, execute)
      : execute()).then(
      async (uploaded) => {
        const server = toServerAttachment(uploaded);
        // Replace the bytes with the server reference durably, so a reload
        // after a partial multi-file success never re-needs the dropped blob.
        if (!scope) await this.blobs.put({
          local_id: localId,
          blob: null,
          result: server,
          filename: record.ref.filename,
          mime_type: record.ref.mime_type,
          created_at: Date.now(),
        });
        if (scope) await scope.lease.validate();
        record.result = server;
        record.promise = null;
        record.controller = null;
        record.file = null;
        this.emit(localId, { upload_state: 'uploaded', upload_progress: 1, upload_error: null });
        return server;
      },
      (error: unknown) => {
        record.promise = null;
        record.controller = null;
        if (!scope?.lease.signal.aborted && !(error instanceof DOMException && error.name === 'AbortError')) {
          this.emit(localId, {
            upload_state: 'failed',
            upload_error: error instanceof Error ? error.message : 'Upload failed.',
          });
        }
        throw error;
      },
    );
    return record.promise;
  }

  private emit(localId: string, patch: Partial<AttachmentRef>): void {
    const record = this.records.get(localId);
    if (record) record.ref = { ...record.ref, ...patch };
    for (const listener of this.listeners) listener(localId, patch);
  }
}

export const attachmentUploads = new AttachmentUploadManager(undefined, undefined, undefined, () => {
  const coordination = documentCoordination();
  const lease = coordination.capture();
  return { coordination, lease, blobs: new AttachmentBlobStore(undefined,
    coordination.storageName(ATTACHMENT_UPLOADS_DB_NAME, lease), lease) };
});
