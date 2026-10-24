import { describe, expect, it } from 'vitest';
import { deliverablePresentation } from './deliverable-presentation';
import type { Deliverable } from './types/api';

describe('shared chat and Library deliverable adaptation', () => {
  it.each([['markdown', 'markdown'], ['html', 'raw_html'], ['plain', 'code']])('retains %s format semantics', (format, block) => {
    const item = { format, content: '<h1>Literal or rendered</h1>' } as Deliverable;
    expect(deliverablePresentation(item)).toMatchObject({ blocks: [{ type: block, content: item.content }] });
  });
  it('preserves canonical rich payload and markdown TOC metadata', () => {
    const rich = { metadata: { title: 'Report' }, blocks: [{ type: 'markdown', content: 'Body' }] };
    expect(deliverablePresentation({ format: 'rich', rich_payload: rich, content: '' })).toBe(rich);
    expect(deliverablePresentation({ format: 'markdown', content: '# One\n## Two\n## Three' } as Deliverable).metadata).toMatchObject({ toc: { enabled: true } });
  });
});
