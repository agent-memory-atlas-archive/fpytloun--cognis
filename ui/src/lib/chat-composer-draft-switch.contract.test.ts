import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const pageSource = readFileSync(resolve('src/routes/(app)/chat/[conversationId]/+page.svelte'), 'utf8');

describe('composer draft swap on conversation switch', () => {
  it('swaps the native value and re-measures the textarea height', () => {
    const start = pageSource.indexOf('// Sync composer draft with the active conversation.');
    expect(start).toBeGreaterThan(-1);
    const effect = pageSource.slice(start, pageSource.indexOf('});', start));
    expect(effect).toContain('composer = loaded;');
    expect(effect).toContain('composerElement.value = loaded;');
    expect(effect).toContain('tick().then(syncComposerHeight)');
  });
});
