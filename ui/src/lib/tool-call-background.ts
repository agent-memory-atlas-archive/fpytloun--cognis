import { isActiveToolStatus, type ToolCallTimelineItem } from '$lib/timeline-render-model';
import type { TimelineScope } from '$lib/chat-v2/types';

/** Tools whose running foreground calls the executor can hand off to a background job. */
const BACKGROUNDABLE_TOOL_NAMES = new Set(['bash']);

/**
 * Return the conversation that owns a running tool call the user may move to the
 * background, or `null` when the action does not apply.
 *
 * The backend remains authoritative: it only accepts calls recorded in the
 * conversation's active turn and the executor rejects calls that already finished
 * or already run in the background.
 */
export function backgroundableToolCallConversationId(
  item: Pick<ToolCallTimelineItem, 'toolName' | 'status' | 'arguments' | 'reconstructed'>,
  scope: TimelineScope | null | undefined
): string | null {
  if (!BACKGROUNDABLE_TOOL_NAMES.has(item.toolName.toLowerCase())) return null;
  if (item.status !== 'started' || !isActiveToolStatus(item.status)) return null;
  if (item.reconstructed) return null;
  if (item.arguments?.run_in_background === true) return null;
  const conversationId = scope?.conversation_id;
  return typeof conversationId === 'string' && conversationId ? conversationId : null;
}
