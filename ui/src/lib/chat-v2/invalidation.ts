import type { WebSocketScopeInvalidatedEvent } from '$lib/types/api';
import type { TimelineScope } from './types';

type TimelineInvalidation = Partial<Pick<WebSocketScopeInvalidatedEvent,
  'scope_key' | 'conversation_id' | 'session_id' | 'task_id' | 'step_run_id'
>> & { reason?: string };

/** A notification is a read hint, never permission to copy another scope's data. */
export function invalidatesTimeline(scope: TimelineScope, event: TimelineInvalidation): boolean {
  if (scope.missing_stream) return false;
  if (event.reason === 'executor_state_changed' || event.reason === 'schedule_action_changed') return false;
  if (event.conversation_id && scope.conversation_id !== event.conversation_id) return false;
  if (event.scope_key && event.scope_key !== scope.key) return false;
  if (event.step_run_id && event.step_run_id !== scope.step_run_id) return false;
  if (event.session_id && event.session_id !== scope.session_id) return false;
  if (event.task_id && event.task_id !== scope.task_id) return false;
  if (event.scope_key || event.step_run_id || event.session_id || event.task_id) return true;
  if (event.conversation_id) return scope.kind === 'conversation';
  // Existing unrouted notifications (including future reasons) conservatively
  // wake canonical readers. Opaque post-append tokens are authorized server-side
  // per socket; keep this compatibility until producers send explicit scope keys.
  return true;
}
