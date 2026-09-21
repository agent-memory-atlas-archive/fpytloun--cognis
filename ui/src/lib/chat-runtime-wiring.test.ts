import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const page = readFileSync(
  'src/routes/(app)/chat/[conversationId]/+page.svelte',
  'utf8',
);

function body(name: string): string {
  const start = page.indexOf(`  function ${name}(`);
  expect(start).toBeGreaterThanOrEqual(0);
  const end = page.indexOf('\n  function ', start + 1);
  return page.slice(start, end < 0 ? undefined : end);
}

describe('open chat runtime ownership wiring', () => {
  it.each([
    'mergeConversationList',
    'mergeAgentDirectChats',
    'applySidebarConversationUpsert',
  ])('reconciles %s through the timeline owner after merging rows', (name) => {
    expect(body(name)).toContain('reconcileOpenConversationRuntime();');
  });

  it('reconciles every representation and uses coalesced canonical recovery', () => {
    const reconcile = body('reconcileOpenConversationRuntime');
    expect(reconcile).toContain('chatV2OwnsActiveConversation(currentConversation.conversation_id)');
    expect(reconcile).toContain('reconcileConversationWithChatRuntime');
    expect(reconcile).toContain('awaitingAssistantStart');
    expect(reconcile).toContain('conversations.map(reconcile)');
    expect(reconcile).toContain('conversation: reconcile(item.conversation)');
    expect(reconcile).toContain('scheduleChatV2CanonicalRecovery(');
    expect(reconcile).not.toContain('recoverChatV2Snapshot(');
    expect(reconcile).toContain('turnInProgress = reconciled.has_active_turn');
  });
});
