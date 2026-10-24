import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, expect, it } from 'vitest';
import NavigationAttentionBadge from './NavigationAttentionBadge.svelte';

afterEach(cleanup);
const badge = { count: 123, tone: 'rose' as const, label: '123 conversations requiring attention' };

it('shows the exact accessible numeric count in expanded rows', () => {
  render(NavigationAttentionBadge, { badge });
  expect(screen.getByLabelText(badge.label).textContent).toBe('123');
  expect(screen.getByTestId('navigation-attention-count').className).toContain('text-danger');
});
it('shows only a colored accessible dot when collapsed', () => {
  render(NavigationAttentionBadge, { badge, collapsed: true });
  expect(screen.getByTestId('navigation-attention-dot').textContent).toBe('');
  expect(screen.getByLabelText(badge.label).className).toContain('bg-danger');
});
it('hides zero and missing badges', () => {
  const { rerender } = render(NavigationAttentionBadge, { badge: { ...badge, count: 0 } });
  expect(screen.queryByLabelText(badge.label)).toBeNull();
  void rerender({ badge: undefined });
  expect(screen.queryByTestId('navigation-attention-count')).toBeNull();
});
