import { describe, expect, it } from 'vitest';
import { navigationAttention } from './navigation-attention';
import type { NavigationChatGroup, NavigationSummary } from './types/api';
import { partitionSidebarConversationLanes } from './conversation-sidebar';
import type { Conversation } from './types/api';

const group = (values: Partial<NavigationChatGroup> = {}): NavigationChatGroup => ({
  active_session_status: null, active_session_completion_reason: null, session_observed: false,
  has_unread: false, is_active: false, pending_notification_types: [], count: 1, ...values,
});
const summary = (chat_groups: NavigationChatGroup[] = []): NavigationSummary => ({
  chat_groups, dashboard: { total: 0, critical: 0, warning: 0, info: 0, truncated: false },
  schedules: 0, tasks: 0,
});

describe('main navigation attention', () => {
  it('suppresses old-backend chat summaries without reliable Waiting inputs', () => {
    const data = summary([
      group({ is_active: undefined, has_unread: true, active_session_status: 'paused', count: 31 }),
      group({ is_active: undefined, pending_notification_types: ['question'] }),
    ]);
    data.tasks = 2;
    expect(navigationAttention(data)['/chat']).toMatchObject({ count: 0, tone: 'default' });
    expect(navigationAttention(data)['/tasks'].count).toBe(2);
  });
  it('counts conversations once and uses the highest conversation tone', () => {
    const result = navigationAttention(summary([
      group({ has_unread: true, count: 10 }),
      group({ has_unread: true, pending_notification_types: ['gate'], count: 2 }),
      group({ has_unread: true, pending_notification_types: ['escalation', 'credential_request'] }),
      group({ active_session_status: 'failed', session_observed: true }),
      group({ count: 50 }),
    ]));
    expect(result['/chat'].count).toBe(13);
    expect(result['/chat'].tone).toBe('rose');
  });
  it('clears observed outcomes but retains unresolved input and new unread activity', () => {
    const result = navigationAttention(summary([
      group({ active_session_status: 'failed', session_observed: true }),
      group({ active_session_status: 'failed', session_observed: true, has_unread: true }),
      group({ active_session_status: 'completed', active_session_completion_reason: 'unexpected' }),
      group({ session_observed: true, pending_notification_types: ['auth_challenge'] }),
    ]));
    expect(result['/chat']).toMatchObject({ count: 2, tone: 'amber' });
  });
  it('does not count session lifecycle attention without Waiting eligibility', () => {
    const data = summary([
      group({ active_session_status: 'paused', count: 31 }),
      group({ active_session_status: 'failed' }),
      group({ active_session_status: 'completed', active_session_completion_reason: 'unexpected' }),
    ]);
    expect(navigationAttention(data)['/chat']).toMatchObject({ count: 0, tone: 'default' });
  });
  it('matches the Waiting group across unread, active, and actionable states', () => {
    const groups = [
      group({ is_active: true, has_unread: true }),
      group({ is_active: true, pending_notification_types: ['step_question'] }),
      group({ has_unread: true }),
      group({ active_session_status: 'paused' }),
      group({ pending_notification_types: ['question'] }),
      group({ pending_notification_types: ['gate'] }),
      group({ active_session_status: 'failed' }),
    ];
    const conversations = groups.map((g, i) => ({
      ...g, conversation_id: `chat-${i}`, has_active_turn: g.is_active ?? false,
    } as unknown as Conversation));
    const waiting = partitionSidebarConversationLanes(conversations).waiting;
    expect(waiting).toHaveLength(3);
    expect(navigationAttention(summary(groups))['/chat'].count).toBe(waiting.length);
  });
  it('combines dashboard issues and unread inbox with provider notices', () => {
    const data = summary();
    data.dashboard = { total: 8, critical: 0, warning: 2, info: 6, truncated: false };
    data.schedules = 4;
    data.tasks = 12;
    expect(navigationAttention(data, 3, [{ severity: 'critical' }])).toMatchObject({
      '/': { count: 12, tone: 'rose' },
      '/schedules': { count: 4, tone: 'rose' },
      '/tasks': { count: 12, tone: 'amber' },
    });
  });
  it('returns zero counts when there is nothing requiring attention', () => {
    expect(Object.values(navigationAttention(null)).every((badge) => badge.count === 0)).toBe(true);
  });
});
