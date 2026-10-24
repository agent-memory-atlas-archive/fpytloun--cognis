import { describe, expect, it, vi } from 'vitest';

import type { AttachmentRef } from '$lib/types/api';
import { AttachmentBlobStore, type StoredAttachmentBlob } from './attachment-blobs';
import { IDBFactory } from 'fake-indexeddb';
import { sameSubmissionInput } from './submission-input';
import {
  AttachmentUploadError,
  AttachmentUploadManager,
  isLocalAttachment,
  toServerAttachment,
  type UploadTransport,
} from './attachment-uploads';
import { isRetryableSendError } from './outbox-retry';
import type { DocumentLease } from '$lib/document-coordination';

function testLease(): DocumentLease & { revoke(): void } {
  const controller = new AbortController();
  const assertCurrent = () => controller.signal.throwIfAborted();
  return { owner: 'attachment-test-owner', epoch: 'attachment-test-epoch', signal: controller.signal,
    assertCurrent, async validate() { assertCurrent(); }, revoke() { controller.abort(new Error('owner revoked')); } };
}

class MemoryBlobs {
  readonly records = new Map<string, StoredAttachmentBlob>();
  failPut = false;
  async put(record: StoredAttachmentBlob): Promise<boolean> {
    if (this.failPut) return false;
    this.records.set(record.local_id, record);
    return true;
  }
  async get(localId: string): Promise<StoredAttachmentBlob | null> {
    return this.records.get(localId) ?? null;
  }
  async delete(localId: string): Promise<void> {
    this.records.delete(localId);
  }
  async prune(): Promise<void> {}
}

function serverRef(filename: string): AttachmentRef {
  return { artifact_id: `art_${filename}`, kind: 'image', mime_type: 'image/png', filename, size_bytes: 3 };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function manager(transport: UploadTransport, blobs = new MemoryBlobs()) {
  let n = 0;
  return {
    blobs,
    uploads: new AttachmentUploadManager(blobs as unknown as AttachmentBlobStore, transport, () => `id${++n}`),
  };
}

const file = () => new File(['abc'], 'photo.png', { type: 'image/png' });

describe('AttachmentUploadManager', () => {
  it('retains staged logical identity across real byte/receipt persistence and progress patches', async () => {
    const factory = new IDBFactory(), lease = testLease(), upload = deferred<AttachmentRef>();
    const blobs = new AttachmentBlobStore(() => factory, 'logical-upload', lease);
    const transport = vi.fn<UploadTransport>(() => upload.promise);
    const uploads = new AttachmentUploadManager(blobs, transport);
    const ref = uploads.stage(file());
    const input = { text: 'image', attachments: [ref], chat_mode: null };
    await uploads.prepare([ref], lease);
    expect(sameSubmissionInput(input, {
      ...input, attachments: [{ ...ref, upload_progress: 0.5, upload_state: 'uploading' }],
    })).toBe(true);
    upload.resolve(serverRef('photo.png'));
    const resolved = await uploads.resolve(ref);
    expect(resolved.artifact_id).toBe('art_photo.png');
    const persisted = await blobs.get(ref.local_id!);
    expect(persisted?.result?.artifact_id).toBe(resolved.artifact_id);
    const reload = new AttachmentUploadManager(new AttachmentBlobStore(() => factory, 'logical-upload', lease), transport);
    expect(await reload.resolve(ref)).toEqual(resolved);
    expect(transport).toHaveBeenCalledOnce();
    expect(sameSubmissionInput(input, {
      ...input, attachments: [{ ...ref, local_id: crypto.randomUUID() }],
    })).toBe(false);
  });
  it('preparation waits for byte commit, without waiting for upload or uploading twice', async () => {
    const blobs = new MemoryBlobs(), committed = deferred<boolean>();
    const originalPut = blobs.put.bind(blobs);
    vi.spyOn(blobs, 'put').mockImplementation(async (record) => {
      const ok = await committed.promise;
      return ok && originalPut(record);
    });
    const transport = vi.fn<UploadTransport>(() => new Promise(() => {}));
    const { uploads } = manager(transport, blobs);
    const ref = uploads.stage(file()), lease = testLease();
    const done = vi.fn();
    const preparing = uploads.prepare([ref], lease).then(done);
    await Promise.resolve();
    expect(done).not.toHaveBeenCalled();
    expect(transport).not.toHaveBeenCalled();
    committed.resolve(true);
    await preparing;
    await uploads.prepare([ref], lease);
    expect(transport).toHaveBeenCalledOnce();
  });

  it('refuses unavailable bytes even when the UI claims the upload completed', async () => {
    const blobs = new MemoryBlobs();
    blobs.failPut = true;
    const { uploads } = manager(vi.fn<UploadTransport>(() => new Promise(() => {})), blobs);
    const ref = uploads.stage(file());
    await expect(uploads.prepare([{ ...ref, upload_state: 'uploaded' }], testLease()))
      .rejects.toMatchObject({ code: 'upload_storage_unavailable' });
  });

  it('authenticates and commits a library receipt, then reuses it after reload without bytes', async () => {
    const blobs = new MemoryBlobs(), ref = serverRef('library.png');
    const verify = vi.fn(async (id: string) => ({ artifact_id: id, url: 'not-persisted', expires_at: null }));
    const uploads = new AttachmentUploadManager(blobs as unknown as AttachmentBlobStore, vi.fn(),
      undefined, undefined, verify);
    expect(await uploads.isDurable(ref)).toBe(false);
    await uploads.prepare([ref], testLease());
    expect(await uploads.isDurable(ref)).toBe(true);
    const afterReload = new AttachmentUploadManager(blobs as unknown as AttachmentBlobStore, vi.fn(),
      undefined, undefined, verify);
    await afterReload.prepare([ref], testLease());
    expect(verify).toHaveBeenCalledOnce();
    expect(blobs.records.get(`server:${ref.artifact_id}`)).toMatchObject({ blob: null, result: ref });
    expect(JSON.stringify([...blobs.records.values()])).not.toContain('not-persisted');
  });

  it('rejects library receipt write failures and unauthorized artifact ids', async () => {
    const blobs = new MemoryBlobs(), ref = serverRef('library.png');
    blobs.failPut = true;
    const verify = vi.fn(async (id: string) => ({ artifact_id: id, url: '', expires_at: null }));
    const uploads = new AttachmentUploadManager(blobs as unknown as AttachmentBlobStore, vi.fn(),
      undefined, undefined, verify);
    await expect(uploads.prepare([ref], testLease())).rejects.toMatchObject({ code: 'upload_storage_unavailable' });
    expect(await uploads.isDurable(ref)).toBe(false);
    verify.mockRejectedValueOnce(new Error('Forbidden'));
    await expect(uploads.prepare([ref], testLease())).rejects.toThrow('Forbidden');
  });

  it('does not persist an authenticated response after owner revocation', async () => {
    const blobs = new MemoryBlobs(), ref = serverRef('library.png'), lease = testLease();
    const verified = deferred<{ artifact_id: string; url: string; expires_at: null }>();
    const verify = vi.fn(() => verified.promise);
    const uploads = new AttachmentUploadManager(blobs as unknown as AttachmentBlobStore, vi.fn(),
      undefined, undefined, verify);
    const preparing = uploads.prepare([ref], lease);
    const rejected = expect(preparing).rejects.toThrow('owner revoked');
    await vi.waitFor(() => expect(verify).toHaveBeenCalledOnce());
    lease.revoke();
    verified.resolve({ artifact_id: ref.artifact_id, url: '', expires_at: null });
    await rejected;
    expect(blobs.records.size).toBe(0);
  });

  it('stages a local placeholder immediately and reports progress', async () => {
    const pending = deferred<AttachmentRef>();
    const transport = vi.fn<UploadTransport>(async (_blob, _name, options) => {
      options.onProgress(0.5);
      return pending.promise;
    });
    const { uploads, blobs } = manager(transport);
    const patches: Array<Partial<AttachmentRef>> = [];
    uploads.onChange((_id, patch) => patches.push(patch));

    const ref = uploads.stage(file());

    expect(ref).toMatchObject({ artifact_id: 'local:id1', local_id: 'id1', upload_state: 'uploading', filename: 'photo.png' });
    expect(isLocalAttachment(ref)).toBe(true);
    await Promise.resolve();
    expect(patches).toContainEqual({ upload_progress: 0.5 });
    expect(await uploads.isDurable(ref)).toBe(true);

    pending.resolve(serverRef('photo.png'));
    await expect(uploads.resolve(ref)).resolves.toEqual(serverRef('photo.png'));
    expect(transport).toHaveBeenCalledTimes(1);
    expect(patches.at(-1)).toMatchObject({ upload_state: 'uploaded' });
    // Bytes are replaced by the durable server reference until admission.
    expect(blobs.records.get('id1')).toMatchObject({ blob: null, result: serverRef('photo.png') });
    uploads.forget([ref]);
    await Promise.resolve();
    expect(blobs.records.size).toBe(0);
  });

  it('reuses persisted results after a reload following a partial multi-file success', async () => {
    const blobs = new MemoryBlobs();
    const transport = vi.fn<UploadTransport>()
      .mockResolvedValueOnce(serverRef('a.png'))
      .mockRejectedValueOnce(new AttachmentUploadError('Network error', { status: 0 }));
    const first = manager(transport, blobs);
    const a = first.uploads.stage(new File(['a'], 'a.png', { type: 'image/png' }));
    const b = first.uploads.stage(new File(['b'], 'b.png', { type: 'image/png' }));
    await expect(first.uploads.resolveAll([a, b])).rejects.toBeInstanceOf(AttachmentUploadError);
    await new Promise((resolve) => setTimeout(resolve, 0));

    const retry = vi.fn<UploadTransport>(async () => serverRef('b.png'));
    const afterReload = new AttachmentUploadManager(blobs as unknown as AttachmentBlobStore, retry);
    await expect(afterReload.resolveAll([a, b])).resolves.toEqual([serverRef('a.png'), serverRef('b.png')]);
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it('resolve awaits the in-flight upload instead of uploading twice', async () => {
    const pending = deferred<AttachmentRef>();
    const transport = vi.fn<UploadTransport>(() => pending.promise);
    const { uploads } = manager(transport);
    const ref = uploads.stage(file());
    const resolving = uploads.resolveAll([ref, serverRef('existing.png')]);
    pending.resolve(serverRef('photo.png'));
    await expect(resolving).resolves.toEqual([serverRef('photo.png'), serverRef('existing.png')]);
    expect(transport).toHaveBeenCalledTimes(1);
  });

  it('re-uploads from the durable blob after a reload', async () => {
    const blobs = new MemoryBlobs();
    const first = manager(vi.fn<UploadTransport>(() => new Promise(() => undefined)), blobs);
    const ref = first.uploads.stage(file());
    await Promise.resolve();

    const transport = vi.fn<UploadTransport>(async () => serverRef('photo.png'));
    const afterReload = new AttachmentUploadManager(blobs as unknown as AttachmentBlobStore, transport);
    await expect(afterReload.resolve(ref)).resolves.toEqual(serverRef('photo.png'));
    expect(transport).toHaveBeenCalledTimes(1);
  });

  it('fails permanently when the file is gone after a reload', async () => {
    const { uploads } = manager(vi.fn<UploadTransport>());
    const missing: AttachmentRef = { ...serverRef('x.png'), artifact_id: 'local:gone', local_id: 'gone' };
    const error = await uploads.resolve(missing).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(AttachmentUploadError);
    expect(isRetryableSendError(error)).toBe(false);
  });

  it('marks network failures retryable and retries on demand', async () => {
    const transport = vi.fn<UploadTransport>()
      .mockRejectedValueOnce(new AttachmentUploadError('Network error', { status: 0 }))
      .mockResolvedValueOnce(serverRef('photo.png'));
    const { uploads } = manager(transport);
    const states: Array<string | undefined> = [];
    uploads.onChange((_id, patch) => { if (patch.upload_state) states.push(patch.upload_state); });
    const ref = uploads.stage(file());
    const error = await uploads.resolve(ref).catch((caught: unknown) => caught);
    expect(isRetryableSendError(error)).toBe(true);
    expect(states).toContain('failed');
    await expect(uploads.resolve(ref)).resolves.toEqual(serverRef('photo.png'));
  });

  it('reports non-durable staging when blob storage fails', async () => {
    const blobs = new MemoryBlobs();
    blobs.failPut = true;
    const { uploads } = manager(vi.fn<UploadTransport>(() => new Promise(() => undefined)), blobs);
    const ref = uploads.stage(file());
    expect(await uploads.isDurable(ref)).toBe(false);
  });

  it('cancel aborts the upload and drops the blob', async () => {
    let signal: AbortSignal | null = null;
    const transport = vi.fn<UploadTransport>((_b, _n, options) => {
      signal = options.signal;
      return new Promise(() => undefined);
    });
    const { uploads, blobs } = manager(transport);
    const ref = uploads.stage(file());
    await Promise.resolve();
    uploads.cancel(ref.local_id!);
    expect((signal as AbortSignal | null)?.aborted).toBe(true);
    await Promise.resolve();
    expect(blobs.records.size).toBe(0);
  });

  it('strips client-only fields from server payloads', () => {
    expect(toServerAttachment({
      ...serverRef('a.png'),
      local_id: 'x',
      upload_state: 'uploaded',
      upload_progress: 1,
      upload_error: null,
      blob_url: 'blob:x',
    })).toEqual(serverRef('a.png'));
  });
});
