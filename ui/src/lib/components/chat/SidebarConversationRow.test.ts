import { render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import type { Conversation } from '$lib/types/api';
import SidebarConversationRow from './SidebarConversationRow.svelte';

const conversation = {
  conversation_id: 'conversation-1',
  title: 'Stable conversation row',
  starred_at: null,
  attention_actions: [],
} as unknown as Conversation;

const commonProps = {
  conversation,
  href: '/chat/conversation-1',
  agentName: 'LaForge',
  avatarState: {
    active: false,
    background: false,
    attention: false,
    unread: false,
    error: false,
    tone: 'default' as const,
    label: 'Idle',
  },
  active: false,
  unread: false,
  canStar: true,
  starBusy: false,
  onNavigate: vi.fn(),
  onToggleStar: vi.fn(),
  onOpenAttention: vi.fn(),
};

describe('SidebarConversationRow', () => {
  it('uses a bounded avatar and two-line title in comfortable mode', () => {
    render(SidebarConversationRow, { ...commonProps, dense: false });
    expect(screen.getByTestId('activity-avatar')).toHaveClass('h-8', 'w-8', 'shrink-0');
    expect(screen.getByText('Stable conversation row')).toHaveClass('line-clamp-2', 'text-sm', 'leading-5');
    expect(screen.getByRole('link')).toHaveClass('items-center');
  });

  it('preserves the compact dense row with inline indicators', () => {
    render(SidebarConversationRow, {
      ...commonProps,
      dense: true,
      showTodoProgress: true,
      todoProgress: [{ content: 'Verify layout', status: 'pending', priority: 'normal' }],
    });
    expect(screen.getByTestId('activity-avatar')).toHaveClass('h-7', 'w-7', 'shrink-0');
    expect(screen.getByText('Stable conversation row')).toHaveClass('whitespace-nowrap', 'text-xs');
    expect(screen.getAllByRole('link')).toHaveLength(1);
    const indicators = screen.getByTestId('sidebar-dense-indicators');
    const todo = screen.getByRole('button', { name: /Conversation todo progress/ });
    const star = screen.getByRole('button', { name: 'Star conversation' });
    expect(indicators).toContainElement(todo);
    expect(indicators).toContainElement(star);
    expect(todo.compareDocumentPosition(star) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('omits the agent-name metadata from comfortable rows', () => {
    render(SidebarConversationRow, { ...commonProps, dense: false });
    expect(screen.queryByText('LaForge')).not.toBeInTheDocument();
  });
});
