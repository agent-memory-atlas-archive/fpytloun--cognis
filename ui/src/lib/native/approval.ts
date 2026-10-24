import type { AttentionActionDetail } from '$lib/types/api';
import { isAttentionActionDetailActionable } from '$lib/attention/actions';

/** Only tool approvals whose optional note can be omitted. Never gates or secret input. */
export function simpleToolApproval(action: AttentionActionDetail): boolean {
  return action.kind === 'escalation' && action.status === 'pending' && isAttentionActionDetailActionable(action)
    && Number.isSafeInteger(action.revision) && action.revision > 0
    && (!action.expires_at || Date.parse(action.expires_at) > Date.now())
    && Boolean(action.display.tool_name)
    && !action.display.questions.length && !action.display.required_fields.length
    && ['approve', 'deny'].every((decision) => action.allowed_actions.some(
      (choice) => choice.action === decision && ['none', 'note'].includes(choice.input)));
}
