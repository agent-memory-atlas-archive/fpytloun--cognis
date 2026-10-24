import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import ImageLightbox from './ImageLightbox.svelte';

describe('ImageLightbox', () => {
  it('portals above chat chrome so its image controls remain visible', async () => {
    const onClose = vi.fn();
    render(ImageLightbox, {
      src: '/test-image.png',
      alt: 'Generated portrait',
      filename: 'portrait.png',
      onClose,
    });

    const dialog = screen.getByRole('dialog', { name: 'portrait.png' });
    await waitFor(() => expect(dialog.parentElement).toBe(document.body));
    expect(screen.getByRole('button', { name: 'Download portrait.png' })).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    const close = screen.getByRole('button', { name: 'Close image viewer' });
    expect(close).toBeInTheDocument();
    await fireEvent.click(close);
    expect(onClose).toHaveBeenCalledOnce();
  });
});
