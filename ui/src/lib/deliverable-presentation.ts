import type { Deliverable } from './types/api';
import { extractMarkdownHeadings } from './markdown';

/** Shared format adaptation for chat and Library; keep raw text and HTML semantics. */
export function deliverablePresentation(deliverable: Pick<Deliverable, 'format' | 'content' | 'rich_payload'>) {
  if (deliverable.format === 'rich' && deliverable.rich_payload) return deliverable.rich_payload;
  return {
    metadata: deliverable.format === 'markdown'
      ? { toc: { enabled: extractMarkdownHeadings(deliverable.content).length >= 3, depth: 4 } }
      : {},
    blocks: [{
      type: deliverable.format === 'plain' ? 'code' : deliverable.format === 'html' ? 'raw_html' : 'markdown',
      content: deliverable.content,
    }],
  };
}
