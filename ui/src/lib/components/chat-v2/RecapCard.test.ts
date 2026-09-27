import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';

import type { RecapTimelineItem } from '$lib/chat-v2/types';
import RecapCard from './RecapCard.svelte';

const recap: RecapTimelineItem = {
  id: 'recap:sess-1:10',
  kind: 'recap',
  sort_key: '0001:0000000010:0000:recap',
  source_refs: [{ store: 'intaris', session_id: 'sess-1', seq: 10, event_type: 'lifecycle' }],
  created_at: '2026-09-26T09:00:00Z',
  stable: true,
  source_session_id: 'sess-1',
  source_seq: 9,
  auto: true,
  stats_version: 4,
  file_diffs_omitted: false,
  scope: 'recent_window',
  text: 'Fixed **rendering** and documented the [change](https://example.org/change).',
  deliverables: [],
  artifacts: [],
  files: [],
};

afterEach(cleanup);

describe('RecapCard', () => {
  it('renders sanitized Markdown with clickable links and no spurious Read more', () => {
    const { container } = render(RecapCard, { item: recap });
    expect(container.querySelector('.chat-markdown strong')?.textContent).toBe('rendering');
    const link = screen.getByRole('link', { name: 'change' });
    expect(link.getAttribute('href')).toBe('https://example.org/change');
    expect(screen.queryByRole('button', { name: /read more|show less/i })).toBeNull();
  });
});
