import { describe, expect, it } from 'vitest';
import type { Agent, Conversation } from '$lib/types/api';
import { conversationYoloEnabled, sessionYoloEnabled } from './yolo-mode';

const agent = { capabilities: { guardrails_backend: 'intaris', maximum_outcome: 'escalate' } } as Agent;
const conversation = { context: { platform_data: {} } } as Conversation;

describe('conversation yolo visibility', () => {
  it('shows agent defaults and conversation overrides', () => {
    expect(conversationYoloEnabled(conversation, agent)).toBe(false);
    expect(conversationYoloEnabled(conversation, {
      ...agent, capabilities: { ...agent.capabilities!, maximum_outcome: 'approve' }
    })).toBe(true);
    expect(conversationYoloEnabled({
      ...conversation,
      context: { ...conversation.context, platform_data: { maximum_outcome_override: 'approve' } }
    }, agent)).toBe(true);
  });

  it('does not show an inactive or unavailable policy', () => {
    expect(conversationYoloEnabled(conversation, null)).toBe(false);
    expect(conversationYoloEnabled({
      ...conversation,
      context: { ...conversation.context, platform_data: { maximum_outcome_override: 'approve' } }
    }, null)).toBe(true);
    expect(conversationYoloEnabled({
      ...conversation,
      context: { ...conversation.context, platform_data: { maximum_outcome_override: 'approve' } }
    }, { ...agent, capabilities: { ...agent.capabilities!, guardrails_backend: 'none' } })).toBe(false);
  });

  it('reads a focused child session policy instead of the parent conversation override', () => {
    const active = { ...conversation, active_session_id: 'parent' };
    expect(sessionYoloEnabled(active, agent, 'child', 'approve')).toBe(true);
    expect(sessionYoloEnabled(active, agent, 'child', 'escalate')).toBe(false);
    expect(sessionYoloEnabled({
      ...active,
      context: { ...active.context, platform_data: { maximum_outcome_override: 'approve' } }
    }, agent, 'child', 'escalate')).toBe(false);
  });
});
