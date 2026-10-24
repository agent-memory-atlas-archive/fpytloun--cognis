import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const list = readFileSync(resolve('src/lib/components/chat-v2/ChatV2TimelineList.svelte'), 'utf8');
const page = readFileSync(resolve('src/routes/(app)/chat/[conversationId]/+page.svelte'), 'utf8');

describe('chat timeline rows', () => {
  // Rows with placeholder heights (content-visibility: auto) resolve to their
  // real size while the user scrolls up and shift the content being read;
  // iOS Safari's scroll anchoring does not correct that reliably.
  it('always render at their real size', () => {
    expect(list).not.toMatch(/content-visibility|contain-intrinsic-size/);
    expect(list).not.toContain('deferOffscreenRows');
    expect(page).not.toContain('deferOffscreenRows');
  });
});
