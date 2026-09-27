import { render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import RichDeliverable from './RichDeliverable.svelte';

describe('Markdown document identity', () => {
  it('renders checklist item text instead of empty timeline entries', () => {
    const { container, getByRole } = render(RichDeliverable, {
      surface: 'standalone',
      payload: { blocks: [{ type: 'checklist', items: [{ text: 'Verify backup' }, { text: 'Check restore', done: true }] }] },
    });
    expect(getByRole('checkbox', { name: 'Verify backup' })).not.toBeChecked();
    expect(getByRole('checkbox', { name: 'Check restore' })).toBeChecked();
    expect(container.querySelector('.rich-incident-timeline')).toBeNull();
  });
  it('keeps the authored heading without a duplicate full-width title', () => {
    const { container } = render(RichDeliverable, {
      surface: 'standalone',
      title: 'Audit report',
      payload: { blocks: [{ type: 'markdown', content: '# Audit\n\n## Findings\n\nDetails.' }] },
    });
    expect(container.querySelector('.rich-toolbar')).toHaveClass('actions-only');
    expect(container.querySelector('.rich-toolbar h1')).toBeNull();
    expect(container.querySelector('.rich-markdown')).toHaveTextContent('Audit');
  });

  it('retains the supplied title when Markdown starts with body text', () => {
    const { container } = render(RichDeliverable, {
      surface: 'standalone',
      title: 'Audit report',
      payload: { blocks: [{ type: 'markdown', content: 'Summary.\n\n# Later heading' }] },
    });
    expect(container.querySelector('.rich-toolbar h1')).toHaveTextContent('Audit report');
  });
});
