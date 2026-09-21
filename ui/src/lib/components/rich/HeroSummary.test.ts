import { render, screen, cleanup } from '@testing-library/svelte';
import { afterEach, expect, it } from 'vitest';
import RichDeliverable from './RichDeliverable.svelte';

afterEach(cleanup);
it('renders a persisted hero dek and gives canonical subtitle precedence', () => {
  const { unmount } = render(RichDeliverable, {
    surface: 'standalone',
    payload: { blocks: [{ type: 'hero', title: 'Operational review', dek: 'Bounded coverage remains active.' }] },
  });
  expect(screen.getByText('Bounded coverage remains active.')).toBeTruthy();
  unmount();
  render(RichDeliverable, {
    surface: 'standalone',
    payload: { blocks: [{ type: 'hero', title: 'Operational review', subtitle: 'Canonical summary', dek: 'Older summary' }] },
  });
  expect(screen.getByText('Canonical summary')).toBeTruthy();
  expect(screen.queryByText('Older summary')).toBeNull();
});
