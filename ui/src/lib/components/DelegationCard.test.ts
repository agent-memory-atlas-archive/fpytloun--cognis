import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import DelegationCard from './DelegationCard.svelte';
import type { DelegationTimelineItem } from '$lib/timeline-render-model';

afterEach(cleanup);

describe('delegation results', () => {
  it.each(['completed', 'running', 'failed'] as const)('renders safe Markdown for %s results', (status) => {
    const item: DelegationTimelineItem = {
      id: 'delegation:sess_review',
      kind: 'delegation',
      taskId: 'sess_review',
      taskLabel: 'Independent review',
      agentId: 'system:code-review',
      usedAgentId: null,
      status,
      result: '### Verdict\n\n**APPROVE**\n\n- Preserves `ordering`\n\n<script>alert(1)</script>\n\n[Unsafe](javascript:alert(1))',
      timestamp: null,
    };
    const { container } = render(DelegationCard, { item });
    expect(screen.getByRole('heading', { name: 'Verdict' })).toBeTruthy();
    expect(container.querySelector('strong')?.textContent).toBe('APPROVE');
    expect(container.querySelector('li code')?.textContent).toBe('ordering');
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(screen.getByText(status)).toBeTruthy();
    if (status === 'completed') expect(screen.queryByText('Working...')).toBeNull();
  });
});
