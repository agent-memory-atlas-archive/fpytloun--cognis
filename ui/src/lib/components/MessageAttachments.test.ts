import { fireEvent, render, screen } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import MessageAttachments from './MessageAttachments.svelte';

const mocks = vi.hoisted(() => ({
  signedUrl: vi.fn(),
  textPreview: vi.fn(),
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
      url: 'https://cognis.test/signed-html-view',
      mode: 'view',
      expires_at: null,
    });
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);

    render(MessageAttachments, {
      attachments: [{
        artifact_id: 'att_html',
        kind: 'file',
        mime_type: 'text/html',
        filename: 'report.html',
        size_bytes: 42,
      }],
    });

    await fireEvent.click(screen.getByRole('button', { name: 'Preview report.html' }));

    const iframe = await screen.findByTitle('Preview of report.html');
    expect(iframe.getAttribute('src')).toBe('https://cognis.test/signed-html-view');
    expect(mocks.signedUrl).toHaveBeenCalledWith('att_html', 3600, 'view');
    expect(open).not.toHaveBeenCalled();
    open.mockRestore();
  });
});
