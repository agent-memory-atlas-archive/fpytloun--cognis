import type { Agent, Conversation } from '$lib/types/api';

/** The conversation override wins over the agent default, including after rotation. */
export function conversationYoloEnabled(
  conversation: Conversation | null,
  agent: Agent | null
): boolean {
  if (!conversation || agent?.capabilities?.guardrails_backend === 'none') return false;
  return conversation.context?.platform_data?.maximum_outcome_override === 'approve'
    || agent?.capabilities?.maximum_outcome === 'approve';
}

/** Historical/child session details use that session's persisted Intaris policy. */
export function sessionYoloEnabled(
  conversation: Conversation | null,
  agent: Agent | null,
  focusedSessionId: string | null,
  maximumOutcome: string | null | undefined
): boolean {
  if (focusedSessionId && focusedSessionId !== conversation?.active_session_id) {
    return maximumOutcome === 'approve';
  }
  return conversationYoloEnabled(conversation, agent);
}
