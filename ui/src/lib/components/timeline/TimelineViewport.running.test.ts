import { render, screen } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TimelineViewport from './TimelineViewport.svelte';

describe('read-only timeline running feedback', () => {
  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      disconnect() {}
    });
  });

  it('shows only three accessible, unboxed dots while running and removes them on completion', async () => {
    const view = render(TimelineViewport, { items: [], live: true });
    const indicator = screen.getByRole('status', { name: 'Turn running' });
    expect(indicator).toHaveTextContent('');
    expect(indicator.querySelectorAll('.animate-bounce')).toHaveLength(3);
    expect(indicator.querySelectorAll('.motion-reduce\\:animate-none')).toHaveLength(3);
    expect(indicator.querySelector('.rounded-full.border')).toBeNull();
    expect(screen.queryByRole('navigation', { name: 'Live tail controls' })).toBeNull();
    await view.rerender({ items: [], live: false });
    expect(screen.queryByTestId('timeline-running-indicator')).not.toBeInTheDocument();
  });

  it('keeps jump-to-latest navigation when reading older messages', () => {
    render(TimelineViewport, { items: [], live: true, userScrolledUp: true });
    expect(screen.getByRole('button', { name: 'Scroll to latest' })).toBeInTheDocument();
    expect(screen.queryByTestId('timeline-running-indicator')).not.toBeInTheDocument();
  });
});
