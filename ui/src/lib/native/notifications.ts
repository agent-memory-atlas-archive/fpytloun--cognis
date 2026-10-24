import { get } from 'svelte/store';
import { api } from '$lib/api/client';
import { auth } from '$lib/stores/auth';
import { inbox } from '$lib/stores/inbox';
import { wsClient } from '$lib/ws/client';
import { normalizeAttention, normalizeNotification, notificationPath, notificationText, type NotificationIntent } from '$lib/notification-events';
import { hostAllowsObservation, postNative } from './host';
import { simpleToolApproval } from './approval';
import { addToast } from '$lib/stores/toasts';
import { notificationAvatar } from './notification-avatar';
import { nativeAgents } from './catalogue';

export function observedConversation(path: string, search: string): string | null {
  const full = /^\/chat\/([A-Za-z0-9_-]+)$/.exec(path);
  return full?.[1] ?? (path === '/native-pinned' ? new URLSearchParams(search).get('conversation') : null);
}

/** One bounded presentation consumer on the existing authenticated root/socket/inbox. */
export function installResidentNotifications(navigate: (path: string) => Promise<unknown>) {
  let alive = true, generation = 0, account: string | null = null, scope = '';
  let inboxReady = false;
  const seen = new Set<string>();
  const approvals = new Map<string, { revision: number; submissionId: string; used: boolean }>();
  let pendingReview: { account: string; intent: NotificationIntent } | null = null;
  const remember = (id: string) => {
    if (seen.has(id)) return false;
    seen.add(id);
    if (seen.size > 512) seen.delete(seen.values().next().value!);
    return true;
  };
  const current = (epoch: number, owner: string | null) => alive && epoch === generation
    && owner === account && get(auth).status === 'authenticated' && !get(auth).offline;
  const suppressed = (intent: NotificationIntent) => intent.kind === 'chat' && hostAllowsObservation()
    && observedConversation(window.location.pathname, window.location.search) === intent.target;
  const deliver = async (intent: NotificationIntent) => {
    const epoch = generation, owner = account;
    if (!owner || !current(epoch, owner) || !remember(intent.id)) return;
    let title = notificationText(intent.title, 80) || 'Cognis', subtitle = '', body = intent.body || 'Open Cognis to review.';
    let sender: { id: string; name: string; png: string | null } | null = null;
    let actionId = intent.actionId;
    let approval: { actionId: string; revision: number; submissionId: string } | null = null;
    if (intent.kind === 'chat') {
      try {
        const conversation = await api.conversations.detail(intent.target, { includeState: false, includeAttentionActions: !intent.terminal });
        if (intent.terminal && conversation.context?.type !== 'web') return;
        if (intent.terminal && conversation.has_unread === false) return;
        if (!actionId && !intent.terminal) {
          actionId = conversation.attention_actions?.find(
            (action) => intent.id === `notification:${action.source.notification_id}`)?.action_id;
        }
        subtitle = notificationText(intent.title || conversation.title, 160);
        const agent = get(nativeAgents).find((item) => item.agent_id === conversation.agent_id);
        title = notificationText(conversation.agent_display_name || agent?.display_name || agent?.name, 80) || 'Cognis';
        if (intent.reply && conversation.agent_id && title !== 'Cognis') {
          sender = { id: conversation.agent_id, name: title,
            png: await notificationAvatar(conversation.agent_avatar_url || agent?.avatar_url) };
        }
      } catch { return; }
    }
    if (intent.kind === 'task') {
      try {
        const task = await api.tasks.detail(intent.target);
        subtitle = notificationText(intent.title || task.title, 160);
        const agent = get(nativeAgents).find((item) => item.agent_id === task.agent_id);
        title = notificationText(agent?.display_name || agent?.name, 80) || 'Cognis';
        body = intent.body || notificationText(`Task ${task.status}.`);
      } catch { return; }
    }
    if (actionId) {
      try {
        const action = await api.attentionActions.get(actionId);
        // Never preview arguments, reasoning, credential values or auth fields.
        if (simpleToolApproval(action) && action.action_id === actionId) {
          body = notificationText(`Tool approval: ${action.display.tool_name}`);
          approval = { actionId: action.action_id, revision: action.revision, submissionId: crypto.randomUUID() };
        }
      } catch { /* Review-only when live authority is unavailable. */ }
    }
    if (!current(epoch, owner) || suppressed(intent)) return;
    if (approval) {
      approvals.set(approval.actionId, { ...approval, used: false });
      if (approvals.size > 512) approvals.delete(approvals.keys().next().value!);
    }
    postNative('notification', { scope, id: intent.id, kind: intent.kind, target: intent.target,
      presentation: { title, subtitle, body, sender, approval } });
  };
  const openReview = async () => {
    const review = pendingReview, epoch = generation, owner = account;
    if (!review || !owner || review.account !== owner || !current(epoch, owner)) return;
    pendingReview = null;
    try {
      const user = await api.auth.me();
      if (!current(epoch, owner) || user.email !== owner) return;
      if (review.intent.kind === 'chat') {
        await api.conversations.detail(review.intent.target, { includeState: false, includeAttentionActions: false });
      } else if (review.intent.kind === 'task') {
        await api.tasks.detail(review.intent.target);
      }
      const path = notificationPath(review.intent);
      if (path && current(epoch, owner)) await navigate(path);
    } catch { /* No stale/offline auth or permission-denied navigation. User can sign in normally. */ }
  };
  const stopAuth = auth.subscribe((state) => {
    const next = state.status === 'authenticated' ? state.user?.email ?? null : null;
    if (next !== account) {
      account = next; generation++; scope = crypto.randomUUID(); seen.clear(); approvals.clear(); inboxReady = false;
      postNative('notification-scope', { scope, account });
    }
    if (next && !state.offline) void openReview();
  });
  const stopEvents = wsClient.subscribe((event) => {
    if (event.type !== 'sidebar_conversation_upsert') return;
    // Canonical owner-wide rows also reach resident clients with no chat
    // subscription. Do not double-consume legacy timeline terminal events.
    const intent = normalizeNotification(event);
    if (intent) void deliver(intent);
    for (const action of normalizeAttention(event)) void deliver(action);
  });
  const stopInbox = inbox.subscribe((state) => {
    if (!account || state.loading || state.error || !state.initialized) return;
    // Initial/reconnect baseline does not replay historical alerts. The canonical
    // inbox owner refreshes on reconnect; the ledger survives that refresh.
    for (const item of state.items) {
      const intent = normalizeNotification(item);
      if (!intent) continue;
      if (!inboxReady) remember(intent.id);
      else void deliver(intent);
    }
    if (state.items.length || !state.loading) inboxReady = true;
  });
  return {
    async act(value: Record<string, unknown>) {
      const epoch = generation, owner = account;
      const id = typeof value.actionId === 'string' ? value.actionId : '';
      const record = approvals.get(id);
      const review = () => {
        // Actions are never retained across sign-in; only the ordinary Review destination is.
        if (alive) {
          addToast('Review this request in Cognis; no approval was confirmed.', 'info');
          const path = get(auth).status === 'authenticated' ? '/notifications' : '/login';
          postNative('notification-review', {});
          void navigate(path);
        }
      };
      if (!owner || !current(epoch, owner) || value.account !== owner || value.scope !== scope
        || !record || value.revision !== record.revision || value.submissionId !== record.submissionId
        || !['approve', 'deny'].includes(String(value.decision))) { review(); return; }
      if (record.used) { review(); return; }
      record.used = true; // No automatic retry, offline queue or replay after sign-in.
      try {
        const user = await api.auth.me();
        if (!current(epoch, owner) || user.email !== owner) { review(); return; }
        const action = await api.attentionActions.get(id);
        if (!current(epoch, owner) || action.action_id !== id || action.revision !== record.revision || !simpleToolApproval(action)) { review(); return; }
        const response = await api.attentionActions.resolve(id, {
          action: String(value.decision), expected_revision: record.revision, submission_id: record.submissionId,
        });
        if (!current(epoch, owner)) return;
        if (response.status !== 'resolved') { review(); return; }
        addToast(value.decision === 'approve' ? 'Tool request approved.' : 'Tool request denied.', 'success');
      } catch { review(); }
    },
    review(value: Record<string, unknown>) {
      if (typeof value.account !== 'string' || typeof value.kind !== 'string' || typeof value.target !== 'string') return;
      const intent = { id: '', kind: value.kind, target: value.target, terminal: false } as NotificationIntent;
      if (!notificationPath(intent)) return;
      pendingReview = { account: value.account, intent };
      if (account === value.account) void openReview();
      else void navigate('/login');
    },
    stop() { alive = false; generation++; pendingReview = null; approvals.clear(); stopAuth(); stopEvents(); stopInbox(); },
  };
}
