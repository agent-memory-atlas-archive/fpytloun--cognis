import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AttachmentSaveButton from './AttachmentSaveButton.svelte';

describe('AttachmentSaveButton', () => {
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('prepares original file then shares on a fresh explicit iPhone tap', async () => {
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue('iPhone');
    const share = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'share', { configurable: true, value: share });
    Object.defineProperty(navigator, 'canShare', { configurable: true, value: () => true });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, blob: async () => new Blob(['original'], { type: 'application/pdf' }),
    }));
    const open = vi.spyOn(window, 'open');
    render(AttachmentSaveButton, {
      filename: 'report.pdf', resolveUrl: async () => '/signed-download',
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Download report.pdf' }));
    const save = await screen.findByRole('button', { name: 'Save/share report.pdf' });
    expect(share).not.toHaveBeenCalled();
    await fireEvent.click(save);
    expect(share).toHaveBeenCalledOnce();
    expect(share.mock.calls[0][0].files[0].name).toBe('report.pdf');
    expect(open).not.toHaveBeenCalled();
  });

  it('reports fetch failure without leaving chat', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
    render(AttachmentSaveButton, { filename: 'file.bin', resolveUrl: async () => '/signed' });
    await fireEvent.click(screen.getByRole('button', { name: 'Download file.bin' }));
    expect(await screen.findByRole('status')).toHaveTextContent('could not be loaded');
  });

  it('does not navigate when iOS cannot share this file type', async () => {
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue('iPhone');
    Object.defineProperty(navigator, 'canShare', { configurable: true, value: () => false });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, blob: async () => new Blob(['data']),
    }));
    const open = vi.spyOn(window, 'open');
    render(AttachmentSaveButton, { filename: 'data.bin', resolveUrl: async () => '/signed' });
    await fireEvent.click(screen.getByRole('button', { name: 'Download data.bin' }));
    expect(await screen.findByRole('status')).toHaveTextContent('cannot save this file in-app');
    expect(open).not.toHaveBeenCalled();
  });

  it('downloads a named blob without a target or navigation', async () => {
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue('Desktop Chrome');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, blob: async () => new Blob(['file']),
    }));
    URL.createObjectURL = vi.fn().mockReturnValue('blob:saved');
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe('file.csv');
      expect(this.target).toBe('');
      expect(this.href).toBe('blob:saved');
    });
    render(AttachmentSaveButton, { filename: 'file.csv', resolveUrl: async () => '/signed' });
    await fireEvent.click(screen.getByRole('button', { name: 'Download file.csv' }));
    await vi.waitFor(() => expect(click).toHaveBeenCalledOnce());
  });
});
