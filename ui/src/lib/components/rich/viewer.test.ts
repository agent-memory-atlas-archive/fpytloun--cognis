import { fireEvent, render, screen } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import RichViewerChrome from './RichViewerChrome.svelte';
import RichDeliverable from './RichDeliverable.svelte';
import { heroBadges } from './hero-badges';
import { setViewerTheme } from './viewer-theme';

describe('viewer chrome', () => {
  beforeEach(() => setViewerTheme('system'));
  it.each([undefined, {}, { icon: { name: 'not-registered', alt: 'Unknown' } }])('omits absent identity %j', (identity) => {
    render(RichViewerChrome, { identity, onCopy: vi.fn() });
    expect(screen.queryByTestId('rich-viewer-identity')).toBeNull();
  });
  it.each([
    { label: 'Engineering' },
    { icon: { name: 'activity', alt: 'Engineering' } },
    { label: 'Engineering', icon: { name: 'activity' } },
  ])('renders authored identity %j', (identity) => {
    render(RichViewerChrome, { identity, onCopy: vi.fn() });
    expect(screen.getByTestId('rich-viewer-identity')).toBeTruthy();
  });
  it('preserves long title and persists an explicit theme', async () => {
    const title = 'A long document title '.repeat(40);
    render(RichViewerChrome, { title, onCopy: vi.fn() });
    expect(screen.getByTitle(title.trim())).toHaveTextContent(title.trim());
    await fireEvent.click(screen.getByRole('button', { name: 'Light theme' }));
    expect(localStorage.getItem('cognis-rich-viewer-theme')).toBe('light');
  });
  it('uses trusted SVG controls in reference order and exposes selection', async () => {
    const { container } = render(RichViewerChrome, { title: 'Report', onCopy: vi.fn(), onDownload: vi.fn() });
    expect(Array.from(container.querySelectorAll('[data-viewer-icon]')).map(el => el.getAttribute('data-viewer-icon')))
      .toEqual(['light', 'dark', 'system', 'download', 'copy']);
    expect(container.querySelector('select')).toBeNull();
    expect(screen.getByRole('button', { name: 'Follow system theme' })).toHaveAttribute('aria-pressed', 'true');
    await fireEvent.click(screen.getByRole('button', { name: 'Dark theme' }));
    expect(screen.getByRole('button', { name: 'Dark theme' })).toHaveAttribute('aria-pressed', 'true');
  });
  it('normalizes typed badges without rendering unknown objects', () => {
    expect(heroBadges([{ label: 'Approved', tone: 'success' }, { label: 'Pending', tone: 'unknown' }, {}, 'Legacy']))
      .toEqual([{ label: 'Approved', tone: 'success' }, { label: 'Pending', tone: 'neutral' }, { label: 'Legacy', tone: 'neutral' }]);
  });
  it('reports clipboard rejection and renders summary KV', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    });
    const { container } = render(RichDeliverable, {
      surface: 'standalone',
      payload: { blocks: [
        { type: 'hero', title: 'Report', badges: [{ label: 'Approved', tone: 'success' }] },
        { type: 'kv', variant: 'summary', items: [{ label: 'Source', value: 'Verified' }] },
      ] },
    });
    expect(container.querySelector('.rich-kv-summary')).toHaveTextContent('Verified');
    expect(container.querySelector('.rich-hero-badges .tone-success')).toHaveTextContent('Approved');
    await fireEvent.click(screen.getByRole('button', { name: 'Copy document' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not copy');
    expect(screen.queryByRole('button', { name: 'Copied' })).toBeNull();
  });
});
