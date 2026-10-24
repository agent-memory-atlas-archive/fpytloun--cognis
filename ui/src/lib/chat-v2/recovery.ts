import type { RuntimeOverlaySnapshot, TimelineItem } from './types';

export interface FailedTurnRecovery {
  turnId: string;
  message: string;
  category?: string | null;
  providerId?: string | null;
  model?: string | null;
}

/** Select the current unresolved failure, independently of viewport pagination. */
export function selectFailedTurnRecovery(
  items: TimelineItem[],
  runtime: RuntimeOverlaySnapshot | null,
  options: { pending?: boolean; suppressedTurnId?: string | null } = {},
): FailedTurnRecovery | null {
  if (options.pending || runtime?.has_active_turn || runtime?.active_turn
    || runtime?.authority?.lifecycle === 'active'
    || runtime?.authority?.lifecycle === 'recoverable') return null;
  const latestUser = items.findLast((item) => item.kind === 'message' && item.role === 'user');
  if (latestUser?.kind === 'message' && !latestUser.turn_id) return null;
  let turnId = latestUser?.kind === 'message' ? latestUser.turn_id : runtime?.authority?.turn_id;
  if (!turnId) return null;
  const tail = latestUser
    ? items.filter((item) => item.sort_key > latestUser.sort_key)
    : items;
  for (const item of tail) {
    if (item.kind === 'message' && item.retry_source_turn_id === turnId && item.turn_id) {
      turnId = item.turn_id;
    }
  }
  if (turnId === options.suppressedTurnId) return null;
  // A retry has its own turn identity even when it reuses the source user message.
  const authority = runtime?.authority;
  if (authority && authority.turn_id !== turnId) return null;
  const failure = tail.findLast((item) => {
    if (item.kind === 'error') return item.turn_id === turnId && item.recoverable;
    return item.kind === 'message'
      && item.role === 'system'
      && item.turn_id === turnId
      && item.notice_kind === 'model_error'
      && (item.notice_scope == null || item.notice_scope === 'failed_turn')
      && item.recoverable !== false
      && item.notice_resolved !== true;
  });
  if (!failure) return null;
  // Assistant commentary before a failure is saved progress, not recovery.
  // A later completed response or recovery notice supersedes the failure.
  if (tail.some((item) => item.sort_key > failure.sort_key && item.kind === 'message'
    && item.turn_id === turnId
    && ((item.role === 'assistant' && !item.partial)
      || (item.notice_kind === 'model_recovery' && item.notice_scope !== 'retry'))
  )) return null;
  const modelFailure = tail.findLast((item) => item.kind === 'message'
    && item.turn_id === turnId && item.notice_kind === 'model_error');
  const provider = modelFailure?.kind === 'message' ? modelFailure : null;
  const category = provider?.reason_class;
  return {
    turnId,
    message: failure.kind === 'error'
      ? failure.error_detail || failure.message || failure.title
      : failure.kind === 'message' ? failure.content : '',
    ...(category ? {
      category,
      providerId: provider?.provider_id,
      model: provider?.model,
    } : {}),
  };
}
