import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { normalizeChatModeTone, optimisticConversationTurnPatch } from './chat-page';

const source = readFileSync(resolve('src/routes/(app)/chat/[conversationId]/+page.svelte'), 'utf8');

describe('main composer optimistic visual-mode projection', () => {
  for (const [submitted, inherited, expected] of [
    [undefined, 'plan', 'plan'],
    [undefined, 'build', 'build'],
    ['default', 'plan', 'default'],
  ] as const) {
    it(`projects ${String(submitted)} with ${inherited} inheritance consistently`, () => {
      // Execute the actual caller's synchronous projection block, with the
      // production mode/patch owners. No duplicate mode-selection algorithm.
      const scope = source.indexOf('if (!isSlashCommand && canProjectSubmission())');
      const start = source.indexOf('awaitingAssistantStart = true;', scope);
      const end = source.indexOf('\n      }', start);
      expect(scope).toBeGreaterThan(-1);
      expect(start).toBeGreaterThan(scope);
      expect(end).toBeGreaterThan(start);
      const patch = vi.fn();
      const run = new Function(
        'optimisticTurnMode', 'persistentChatMode', 'normalizeChatModeTone',
        'optimisticConversationTurnPatch', 'patchConversationInList',
        `let awaitingAssistantStart = false, turnInProgress = false, activeTurnChatMode;
         const sendConversationId = 'synthetic-mode-projection';
         ${source.slice(start, end)}
         return { activeTurnChatMode, awaitingAssistantStart, turnInProgress, optimisticTurnMode };`,
      );
      const result = run(submitted, inherited, normalizeChatModeTone, optimisticConversationTurnPatch, patch);
      expect(result).toEqual({
        activeTurnChatMode: expected, awaitingAssistantStart: true,
        turnInProgress: true, optimisticTurnMode: submitted,
      });
      expect(patch).toHaveBeenCalledExactlyOnceWith(
        'synthetic-mode-projection',
        optimisticConversationTurnPatch(expected),
        { touchLastMessageAt: true },
      );
    });
  }
});
