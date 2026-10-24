import type { CognisWebSocketEvent, InboxItem } from '$lib/types/api';

export interface NotificationIntent {
  id: string;
  kind: 'chat' | 'task' | 'notifications';
  target: string;
  /** Plain message/task terminal alerts exclude managed child work. */
  terminal: boolean;
  title?: string;
  body?: string;
  reply?: boolean;
  actionId?: string;
}
export const notificationIdentifier = (value: unknown): value is string =>
  typeof value === 'string' && /^[A-Za-z0-9_-]{1,160}$/.test(value);

/** Plain bounded presentation, not HTML, tool arguments, transcripts or credential input. */
export function notificationText(value: unknown, limit = 240): string {
  if (typeof value !== 'string') return '';
  // Fail closed for the entire preview: a label may precede a multiline value.
  if (/password|passwd|secret|credential|token|api.?key|authorization|private.?key|recovery.?code|otp|bearer|sk-[A-Za-z0-9]|[A-Za-z0-9_+/=-]{32,}/i.test(value)) return '';
  return value.slice(0, 8192).replace(/```[\s\S]*?(?:```|$)/g, '')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/https?:\/\/\S+|<[^>]*>|[`*_#>]/g, '')
    .replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, ' ')
    .replace(/\s+/g, ' ').trim().slice(0, limit);
}

export function normalizeNotification(event: CognisWebSocketEvent | InboxItem): NotificationIntent | null {
  if ('type' in event && event.type === 'sidebar_conversation_upsert') {
    const conversation = event.conversation;
    if (!conversation || !notificationIdentifier(conversation.conversation_id)
      || conversation.context?.type !== 'web' || conversation.has_active_turn
      || !conversation.has_unread || !conversation.last_message_at
      || !Number.isFinite(Date.parse(conversation.last_message_at))) return null;
    const reply = event.completed_reply;
    if (reply === null) return null;
    if (reply && !notificationIdentifier(reply.message_id)) return null;
    return {
      // Deployed pre-preview controllers emit metadata-only rows. Keep their
      // alert contract, but never invent a reply preview from a later fetch.
      id: `terminal:${conversation.conversation_id}:${reply?.message_id ?? conversation.last_message_at}`,
      kind: 'chat', target: conversation.conversation_id, terminal: true,
      title: notificationText(conversation.title, 160), body: notificationText(reply?.preview), reply: Boolean(reply),
    };
  }
  if ('notification_id' in event && !('type' in event)) {
    if (event.read_at || !notificationIdentifier(event.notification_id)) return null;
    const route = /^\/(chat|tasks)\/([A-Za-z0-9_-]{1,160})$/.exec(event.href);
    return {
      id: `notification:${event.notification_id}`,
      kind: route?.[1] === 'chat' ? 'chat' : route?.[1] === 'tasks' ? 'task' : 'notifications',
      target: route?.[2] ?? '', terminal: false,
      title: notificationText(event.title, 80),
      body: /credential|auth|question/i.test(event.kind) ? 'Open Cognis to review.' : notificationText(event.body),
    };
  }
  if (!('type' in event)) return null;
  if (event.type === 'message_complete' || event.type === 'workflow_completed'
    || event.type === 'workflow_failed' || event.type === 'workflow_cancelled') {
    if (!notificationIdentifier(event.conversation_id)) return null;
    if (event.type === 'message_complete' && event.partial) return null;
    const identity = event.turn_id || (event.type === 'message_complete' ? event.message_id : event.task_id);
    if (!notificationIdentifier(identity)) return null;
    return { id: `terminal:${event.conversation_id}:${identity}`, kind: 'chat', target: event.conversation_id, terminal: true };
  }
  if (['escalation', 'workflow_gate', 'workflow_step_question', 'auth_challenge', 'credential_request'].includes(event.type)) {
    const value = event as { notification_id?: string; conversation_id?: string; managed_origin_conversation_id?: string };
    if (!notificationIdentifier(value.notification_id)) return null;
    const id = value.managed_origin_conversation_id || value.conversation_id;
    return { id: `notification:${value.notification_id}`, kind: notificationIdentifier(id) ? 'chat' : 'notifications',
      target: notificationIdentifier(id) ? id : '', terminal: false };
  }
  return null;
}

export function normalizeAttention(event: CognisWebSocketEvent): NotificationIntent[] {
  if (event.type !== 'sidebar_conversation_upsert') return [];
  return (event.conversation?.attention_actions ?? []).flatMap((action) => {
    if (action.status !== 'pending' || !notificationIdentifier(action.source.notification_id)) return [];
    const target = action.source.managed_origin_conversation_id || action.source.conversation_id;
    return [{ id: `notification:${action.source.notification_id}`, kind: notificationIdentifier(target) ? 'chat' as const : 'notifications' as const,
      target: notificationIdentifier(target) ? target : '', terminal: false,
      title: notificationText(action.title, 160), actionId: action.action_id }];
  });
}

export function notificationPath(intent: Pick<NotificationIntent, 'kind' | 'target'>): string | null {
  if (intent.kind === 'notifications' && intent.target === '') return '/notifications';
  if (!notificationIdentifier(intent.target)) return null;
  if (intent.kind === 'chat') return `/chat/${intent.target}`;
  if (intent.kind === 'task') return `/tasks/${intent.target}`;
  return null;
}
