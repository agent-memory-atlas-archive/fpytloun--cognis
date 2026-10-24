import { render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import StandaloneViewer from './StandaloneViewer.svelte';

describe('standalone selection copy', () => {
  it.each([false, true])('copies Unicode prose as text and HTML (offline=%s)', async (exportMode) => {
    // No owner ID: selection copying must not depend on authenticated sharing.
    const text = 'baterie: kouřový senzor (0 %)';
    const { unmount } = render(StandaloneViewer, {
      viewerProps: {
        surface: 'standalone',
        exportMode,
        content: `${text}\n\nZ-Wave: zkontrolovat napájení.`,
        payload: { blocks: [{ type: 'markdown', content: `${text}\n\nZ-Wave: zkontrolovat napájení.` }] },
      },
    });
    const source = screen.getByText(text);
    const range = document.createRange();
    range.selectNodeContents(source.parentElement!);
    const selection = document.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    const setData = vi.fn();
    const copy = new Event('copy', { bubbles: true, cancelable: true });
    Object.defineProperty(copy, 'clipboardData', { value: { setData } });

    source.dispatchEvent(copy);

    expect(copy.defaultPrevented).toBe(true);
    expect(setData).toHaveBeenCalledWith('text/plain', `${text}\n\nZ-Wave: zkontrolovat napájení.`);
    expect(setData).toHaveBeenCalledWith('text/html', expect.stringContaining(text));
    expect(setData.mock.calls.map(([type]) => type)).toEqual(['text/html', 'text/plain']);

    await unmount();
    setData.mockClear();
    const afterUnmount = new Event('copy', { bubbles: true, cancelable: true });
    Object.defineProperty(afterUnmount, 'clipboardData', { value: { setData } });
    document.dispatchEvent(afterUnmount);
    expect(setData).not.toHaveBeenCalled();
    selection.removeAllRanges();
  });
});
