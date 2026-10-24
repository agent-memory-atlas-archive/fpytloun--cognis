import { CHAT_STORAGE_KEYS, parseStoredMultiFilter } from '$lib/chat-page';
import type { Agent } from '$lib/types/api';

/** Reuse the current chat context, then the Chat app's stored single-agent filter. */
export function preferredNewChatAgentId(
  agents: Agent[],
  currentAgentIds: (string | null | undefined)[] = [],
  fallbackAgentId?: string,
): string {
  const primary = agents.filter((agent) => agent.agent_type === 'primary' && agent.status === 'active');
  const eligible = new Set(primary.map((agent) => agent.agent_id));
  const current = currentAgentIds.find((id) => id && eligible.has(id));
  if (current) return current;
  try {
    const stored = typeof window === 'undefined'
      ? [] : parseStoredMultiFilter(window.localStorage.getItem(CHAT_STORAGE_KEYS.selectedAgent));
    if (stored.length === 1 && eligible.has(stored[0])) return stored[0];
  } catch {
    // Browser storage can be unavailable; keep the normal eligible-agent fallback.
  }
  return fallbackAgentId && eligible.has(fallbackAgentId)
    ? fallbackAgentId : primary[0]?.agent_id ?? '';
}
