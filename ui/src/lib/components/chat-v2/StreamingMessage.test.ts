import { cleanup, render } from '@testing-library/svelte';
import { afterEach, expect, it } from 'vitest';
import type { MessageTimelineItem } from '$lib/chat-v2/types';
import ChatV2TimelineItemRenderer from './ChatV2TimelineItemRenderer.svelte';

afterEach(cleanup);

it('keeps incomplete image syntax hidden in the production renderer and streams later text', async () => {
  const item: MessageTimelineItem = {
    id: 'message_1', message_id: 'message_1', kind: 'message', role: 'assistant',
    content: '![', sort_key: '1', source_refs: [], stable: false,
    partial: true, status: 'running', attachments: [],
  };
  const view = render(ChatV2TimelineItemRenderer, { item });
  expect(view.container.textContent).not.toContain('![');
  await view.rerender({ item: { ...item, content: '## Photo\n\n![Photo](https://example.com/photo.png)' } });
  expect(view.container.querySelector('h2')?.textContent).toBe('Photo');
  expect(view.container.querySelector('img[src="https://example.com/photo.png"]')).not.toBeNull();
  await view.rerender({ item: { ...item, content: '## Photo\n\nNow continuing.' } });
  expect(view.container.textContent).toContain('Now continuing.');
  await view.rerender({ item: { ...item, content: '![', partial: false, status: 'complete', stable: true } });
  expect(view.container.textContent).toContain('![');
});
