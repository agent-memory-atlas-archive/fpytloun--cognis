import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import ShareMenu from './ShareMenu.svelte';

describe('share expiration controls', () => {
  it.each([1, 7, 30, 90])('creates and copies a %s-day link only after selection', async days => {
    const createLink = vi.fn().mockResolvedValue('https://cognis.example.com/share-result');
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    render(ShareMenu, { createLink });
    await fireEvent.click(screen.getByRole('button', { name: 'Share public link' }));
    expect(screen.getByRole('dialog', { name: 'Public link' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Public link' })).toHaveClass('text-strong');
    expect(screen.getByRole('combobox', { name: 'Public link validity' }))
      .toHaveClass('bg-surface', 'text-foreground', 'border-control-border');
    expect(createLink).not.toHaveBeenCalled();
    await fireEvent.change(screen.getByRole('combobox', { name: 'Public link validity' }), { target: { value: String(days) } });
    await fireEvent.click(screen.getByRole('button', { name: 'Create public link' }));
    await waitFor(() => expect(createLink).toHaveBeenCalledWith({ ttl_seconds: days * 86400 }));
    expect(writeText).toHaveBeenCalledWith('https://cognis.example.com/share-result');
    expect(screen.getByRole('textbox', { name: 'Public link URL' })).toHaveValue('https://cognis.example.com/share-result');
    expect(screen.getByRole('textbox', { name: 'Public link URL' })).toHaveClass('bg-surface', 'text-foreground');
  });

  it('uses a timezone-qualified custom date and restores focus on Escape', async () => {
    const createLink = vi.fn().mockResolvedValue('https://cognis.example.com/share-result');
    render(ShareMenu, { createLink });
    const trigger = screen.getByRole('button', { name: 'Share public link' });
    trigger.focus();
    await fireEvent.click(trigger);
    await fireEvent.change(screen.getByRole('combobox', { name: 'Public link validity' }), { target: { value: 'custom' } });
    const date = new Date(Date.now() + 2 * 86400000);
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    await fireEvent.input(screen.getByLabelText('Expiration date and time', { exact: false }), { target: { value: local } });
    await fireEvent.click(screen.getByRole('button', { name: 'Create public link' }));
    await waitFor(() => expect(createLink).toHaveBeenCalledWith({ expires_at: new Date(local).toISOString() }));
    await fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it('rejects expired custom dates and exposes failures without copying', async () => {
    const createLink = vi.fn().mockRejectedValue(new Error('Share denied'));
    render(ShareMenu, { createLink });
    await fireEvent.click(screen.getByRole('button', { name: 'Share public link' }));
    await fireEvent.change(screen.getByRole('combobox', { name: 'Public link validity' }), { target: { value: 'custom' } });
    await fireEvent.input(screen.getByLabelText('Expiration date and time', { exact: false }), { target: { value: '2020-01-01T00:00' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Create public link' }));
    expect(screen.getByRole('alert')).toHaveTextContent('between one minute and 90 days');
    expect(createLink).not.toHaveBeenCalled();
    await fireEvent.change(screen.getByRole('combobox', { name: 'Public link validity' }), { target: { value: '1' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Create public link' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Share denied'));
    expect(screen.getByRole('alert')).toHaveClass('text-danger');
  });
  it('passes explicit download mode for mode-aware document previews', async () => {
    const createLink = vi.fn().mockResolvedValue('https://cognis.test/shared/download');
    render(ShareMenu, { createLink, allowModeChoice: true, defaultMode: 'download' });
    await fireEvent.click(screen.getByRole('button', { name: 'Share public link' }));
    expect(screen.getByRole('combobox', { name: 'Link behavior' })).toHaveValue('download');
    await fireEvent.click(screen.getByRole('button', { name: 'Create public link' }));
    await waitFor(() => expect(createLink).toHaveBeenCalledWith({ ttl_seconds: 604800, mode: 'download' }));
  });
});
