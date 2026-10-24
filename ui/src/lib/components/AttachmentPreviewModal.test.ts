import { render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AttachmentRef } from '$lib/types/api';
import AttachmentPreviewModal from './AttachmentPreviewModal.svelte';

const mocks = vi.hoisted(() => ({
  textPreview: vi.fn(),
}));

vi.mock('$lib/api/client', () => ({
  api: {
    artifacts: {
      textPreview: mocks.textPreview,
    },
  },
}));

function attachment(filename: string, mimeType: string): AttachmentRef {
  return {
    artifact_id: 'att_preview',
    kind: 'file',
    mime_type: mimeType,
    filename,
    size_bytes: 42,
  };
}

describe('AttachmentPreviewModal', () => {
  beforeEach(() => {
    mocks.textPreview.mockReset();
  });
  afterEach(() => vi.unstubAllGlobals());

  it('renders Markdown through the sanitized rich viewer', async () => {
    mocks.textPreview.mockResolvedValue({
      content: '# Preview title\n\n<script>alert("x")</script>',
      filename: 'report.md',
      mime_type: 'text/markdown',
      preview_kind: 'markdown',
      rich_payload: {
        metadata: {},
        blocks: [{ type: 'markdown', content: '# Preview title\n\n<script>alert("x")</script>' }],
      },
      size_bytes: 42,
      truncated: false,
    });

    render(AttachmentPreviewModal, {
      attachment: attachment('report.md', 'text/markdown'),
      kind: 'markdown',
      onClose: vi.fn(),
      resolveDownloadUrl: vi.fn(),
    });

    expect(await screen.findByRole('heading', { name: 'Preview title' })).toBeTruthy();
    expect(screen.getByRole('dialog').querySelector('script')).toBeNull();
  });

  it('renders CSV cells as inert code values in a table', async () => {
    mocks.textPreview.mockResolvedValue({
      content: 'name,value\nAlice,=1+1',
      filename: 'data.csv',
      mime_type: 'text/csv',
      preview_kind: 'csv',
      rich_payload: {
        metadata: {},
        blocks: [{
          type: 'table',
          columns: [{ key: 'column_0', label: 'name' }, { key: 'column_1', label: 'value' }],
          rows: [{
            column_0: { type: 'code', value: 'Alice' },
            column_1: { type: 'code', value: '=1+1' },
          }],
        }],
      },
      size_bytes: 42,
      table: { headers: ['name', 'value'], rows: [['Alice', '=1+1']] },
      truncated: false,
    });

    render(AttachmentPreviewModal, {
      attachment: attachment('data.csv', 'text/csv'),
      kind: 'csv',
      onClose: vi.fn(),
      resolveDownloadUrl: vi.fn(),
    });

    await screen.findByRole('table');
    expect(document.querySelector('td code')?.textContent).toBe('Alice');
    expect(screen.getByText('=1+1')).toBeTruthy();
  });

  it('keeps HTML previews inside a sandboxed modal iframe', async () => {
    const controller = new AbortController();
    const url = new URL(`/api/v1/artifacts/view/attachments/att_preview/page.html?exp=9999999999&sig=${'a'.repeat(64)}`, window.location.origin).href;
    const revoke = vi.fn();
    vi.stubGlobal('URL', class extends URL {
      static createObjectURL = vi.fn(() => 'blob:https://cognis.test/modal-preview');
      static revokeObjectURL = revoke;
    });
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<h1>Preview</h1>', {
      headers: { 'content-type': 'text/html' },
    })));
    const view = render(AttachmentPreviewModal, {
      attachment: attachment('page.html', 'text/html'),
      kind: 'html',
      htmlSource: { url, lease: {
        owner: 'modal-preview', epoch: '1', signal: controller.signal,
        assertCurrent() { controller.signal.throwIfAborted(); },
        async validate() { controller.signal.throwIfAborted(); },
      } },
      onClose: vi.fn(),
      resolveDownloadUrl: vi.fn(),
    });

    await waitFor(() => expect(document.querySelector('iframe')).not.toBeNull());
    const iframe = document.querySelector('iframe');
    expect(iframe?.getAttribute('src')).toBe('blob:https://cognis.test/modal-preview');
    expect(iframe?.getAttribute('sandbox')).toBe('allow-scripts');
    expect(fetch).toHaveBeenCalledWith(url, expect.objectContaining({
      credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer',
    }));
    view.unmount();
    expect(iframe?.isConnected).toBe(false);
    expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:https://cognis.test/modal-preview');
  });
});
