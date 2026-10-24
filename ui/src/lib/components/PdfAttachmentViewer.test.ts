import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import PdfAttachmentViewer from './PdfAttachmentViewer.svelte';

const mocks = vi.hoisted(() => ({
  getPage: vi.fn(), destroy: vi.fn().mockResolvedValue(undefined), getDocument: vi.fn(),
}));
vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => ({
  GlobalWorkerOptions: {}, getDocument: mocks.getDocument,
}));
vi.mock('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url', () => ({ default: '/pdf-worker.mjs' }));

describe('PdfAttachmentViewer', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });
  it('fits pages, navigates the whole document, and destroys resources on close', async () => {
    vi.stubGlobal('ResizeObserver', class {
      constructor(private callback: (entries: unknown[]) => void) {}
      observe() { this.callback([{ contentRect: { width: 390 } }]); }
      disconnect() {}
    });
    const renderPage = vi.fn().mockReturnValue({ promise: Promise.resolve(), cancel: vi.fn() });
    mocks.getPage.mockResolvedValue({
      getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale }),
      render: renderPage,
      cleanup: vi.fn(),
    });
    mocks.getDocument.mockReturnValue({
      promise: Promise.resolve({ numPages: 3, getPage: mocks.getPage }),
      destroy: mocks.destroy,
    });
    const { unmount } = render(PdfAttachmentViewer, { url: '/signed.pdf' });
    await waitFor(() => expect(mocks.getPage).toHaveBeenCalledWith(1));
    await fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(mocks.getPage).toHaveBeenCalledWith(2));
    await fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(mocks.getPage).toHaveBeenCalledWith(3));
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    const canvas = document.querySelector('canvas')!;
    expect(parseFloat(canvas.style.width)).toBeLessThanOrEqual(390);
    await unmount();
    expect(mocks.destroy).toHaveBeenCalledOnce();
  });
});
