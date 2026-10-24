import { conversationAttentionOutcomeTone } from '$lib/chat-page';
import { isSidebarConversationWaiting } from '$lib/conversation-sidebar';
import type { NavigationSummary } from '$lib/types/api';

export type NavigationTone = 'default' | 'amber' | 'rose';
export interface NavigationBadge {
  count: number;
  tone: NavigationTone;
  label: string;
}

export function navigationAttention(
  summary: NavigationSummary | null,
  unreadInbox = 0,
  additionalIssues: { severity: 'critical' | 'warning' | 'info' }[] = [],
): Record<string, NavigationBadge> {
  let chatCount = 0;
  let chatTone: NavigationTone = 'default';
  for (const group of summary?.chat_groups ?? []) {
    // Older summaries lack activity and lane scope; don't invent a Waiting count.
    if (typeof group.is_active !== 'boolean') continue;
    if (!isSidebarConversationWaiting(group, group.is_active)) continue;
    const tone = conversationAttentionOutcomeTone(group);
    chatCount += group.count;
    if (tone === 'rose' || (tone === 'amber' && chatTone === 'default')) chatTone = tone;
  }
  const dashboardCount = (summary?.dashboard.total ?? 0) + unreadInbox + additionalIssues.length;
  const critical = (summary?.dashboard.critical ?? 0) + additionalIssues.filter((issue) => issue.severity === 'critical').length;
  const warning = (summary?.dashboard.warning ?? 0) + additionalIssues.filter((issue) => issue.severity === 'warning').length;
  return {
    '/chat': { count: chatCount, tone: chatTone, label: `${chatCount} conversations with unread activity or requiring attention` },
    '/': { count: dashboardCount, tone: critical ? 'rose' : warning ? 'amber' : 'default', label: `${dashboardCount} unresolved issues or unread notifications` },
    '/schedules': { count: summary?.schedules ?? 0, tone: 'rose', label: `${summary?.schedules ?? 0} unresolved schedule failures` },
    '/tasks': { count: summary?.tasks ?? 0, tone: 'amber', label: `${summary?.tasks ?? 0} paused tasks waiting for input or approval` },
  };
}
