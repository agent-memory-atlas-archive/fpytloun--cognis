import { fireEvent, render, screen } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import MessageAttachments from './MessageAttachments.svelte';
// Lazily imported by the component under test; load it during collection.
import '$lib/components/AttachmentPreviewModal.svelte';

const mocks = vi.hoisted(() => ({
  signedUrl: vi.fn(),
  textPreview: vi.fn(),
}));
vi.mock('$lib/config', () => ({ apiUrl: (path: string) => `https://cognis.test${path}` }));
vi.mock('$lib/document-coordination', () => ({
  documentCoordination: () => ({ capture: () => ({
    owner: 'reader', epoch: '1', signal: new AbortController().signal,
    assertCurrent() {}, async validate() {},
  }) }),
}));

const uploads = vi.hoisted(() => {
  const listeners = new Set<(localId: string, patch: Record<string, unknown>) => void>();
  return {
    listeners,
    state: new Map<string, Record<string, unknown>>(),
    emit(localId: string, patch: Record<string, unknown>) {
      for (const listener of listeners) listener(localId, patch);
    },
  };
});

vi.mock('$lib/chat-v2/attachment-uploads', () => ({
  attachmentUploads: {
    uploadState: (localId: string) => uploads.state.get(localId) ?? null,
    onChange: (listener: (localId: string, patch: Record<string, unknown>) => void) => {
      uploads.listeners.add(listener);
      return () => uploads.listeners.delete(listener);
    },
  },
}));

vi.mock('$lib/api/client', () => ({
  api: {
    artifacts: {
      signedUrl: mocks.signedUrl,
      textPreview: mocks.textPreview,
    },
  },
}));

describe('MessageAttachments', () => {
  beforeEach(() => {
    mocks.signedUrl.mockReset();
    mocks.textPreview.mockReset();
  });

  it('opens HTML preview in the chat modal instead of a new tab', async () => {
    mocks.signedUrl.mockResolvedValue({
      artifact_id: 'att_html',
      url: `https://cognis.test/api/v1/artifacts/view/attachments/att_html/report.html?exp=9999999999&sig=${'a'.repeat(64)}`,
      mode: 'view',
      expires_at: null,
    });
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<h1>Report</h1>', { headers: { 'content-type': 'text/html' } })));
    URL.createObjectURL = vi.fn(() => 'blob:https://cognis.test/6b3a438a-2580-491f-a51e-d7e0bbdc8fd5');
    URL.revokeObjectURL = vi.fn();

    const view = render(MessageAttachments, {
      attachments: [{
        artifact_id: 'att_html',
        kind: 'file',
        mime_type: 'text/html',
        filename: 'report.html',
        size_bytes: 42,
      }],
    });

    const filename = screen.getByRole('button', { name: /^report\.html$/ });
    const row = filename.closest('.bg-surface');
    expect(row).toHaveClass('text-foreground');
    expect(row).not.toHaveClass('bg-inset/40');
    expect(row).toContainElement(screen.getByRole('button', { name: 'Preview report.html' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Preview report.html' }));

    const iframe = await screen.findByTitle('Artifact preview');
    expect(iframe.getAttribute('src')).toMatch(/^blob:/);
    expect(iframe).toHaveAttribute('sandbox', 'allow-scripts');
    expect(mocks.signedUrl).toHaveBeenCalledWith('att_html', 3600, 'view', expect.any(AbortSignal));
    expect(open).not.toHaveBeenCalled();
    open.mockRestore();
    view.unmount(); vi.unstubAllGlobals();
  });

  it('keeps showing live upload progress for a sent message until the upload finishes', async () => {
    uploads.state.set('loc-1', { upload_state: 'uploading', upload_progress: 0.2, upload_error: null });
    render(MessageAttachments, {
      attachments: [{
        artifact_id: 'local:loc-1',
        local_id: 'loc-1',
        kind: 'image',
        mime_type: 'image/png',
        filename: 'photo.png',
        size_bytes: 1000,
        url: 'blob:preview',
        // Snapshot taken at send time: stale progress.
        upload_state: 'uploading',
        upload_progress: 0,
      }],
    });

    expect(await screen.findByRole('status', { name: 'Uploading 20%' })).toBeTruthy();
    expect(mocks.signedUrl).not.toHaveBeenCalled();

    uploads.emit('loc-1', { upload_progress: 0.75 });
    expect(await screen.findByRole('status', { name: 'Uploading 75%' })).toBeTruthy();

    uploads.emit('loc-1', { upload_state: 'uploaded', upload_progress: 1, upload_error: null });
    await vi.waitFor(() => expect(screen.queryByRole('status')).toBeNull());
  });
});
