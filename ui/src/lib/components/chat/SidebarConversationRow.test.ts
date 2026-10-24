import { fireEvent, render, screen } from '@testing-library/svelte';
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
      active: true,
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

  it.each([false, true])('shows the outline only after navigation selects the row (dense=%s)', async (dense) => {
    const onNavigate = vi.fn();
    const { rerender } = render(SidebarConversationRow, { ...commonProps, dense, onNavigate });
    const indicators = screen.getByTestId(dense ? 'sidebar-dense-indicators' : 'sidebar-row-indicators');
    const spacer = indicators.querySelector('span.pointer-events-none');
    expect(spacer).toHaveClass('h-6', 'w-6');
    expect(spacer).toHaveAttribute('aria-hidden', 'true');
    expect(spacer).not.toHaveAttribute('tabindex');
    expect(screen.queryByRole('button', { name: 'Star conversation' })).not.toBeInTheDocument();
    await fireEvent.mouseOver(screen.getByRole('link'));
    await fireEvent.focus(screen.getByRole('link'));
    expect(screen.queryByRole('button', { name: 'Star conversation' })).not.toBeInTheDocument();
    await fireEvent.click(screen.getByRole('link'));
    expect(onNavigate).toHaveBeenCalledTimes(1);
    await rerender({ active: true });
    expect(indicators.querySelector('span.pointer-events-none')).toBeNull();
    expect(screen.getByRole('button', { name: 'Star conversation' })).toBeVisible();
    await rerender({ active: false });
    expect(screen.queryByRole('button', { name: 'Star conversation' })).not.toBeInTheDocument();
  });

  it('always shows the filled star on a starred inactive row', () => {
    render(SidebarConversationRow, {
      ...commonProps, dense: false,
      conversation: { ...conversation, starred_at: '2026-10-17T00:00:00Z' },
    });
    expect(screen.getByRole('button', { name: 'Unstar conversation' })).toBeVisible();
  });

  it.each([false, true])('keeps the title untouched and metadata in trailing indicators (dense=%s)', (dense) => {
    render(SidebarConversationRow, {
      ...commonProps, dense,
      conversation: {
        ...conversation, is_readonly_for_caller: true, agent_display_name: 'Private agent',
        agent_avatar_url: '/api/v1/images/avatar?conversation_id=conversation-1',
        project_name: 'Cognis', project_color: '#38bdf8',
      },
    });
    expect(screen.getByTestId('conversation-project-badge')).toHaveTextContent('Cognis');
    expect(screen.queryByLabelText('Read-only')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Star conversation' })).not.toBeInTheDocument();
    const title = screen.getByText('Stable conversation row');
    expect(title.textContent).toBe(conversation.title);
    expect(title.children).toHaveLength(0);
    const indicators = screen.getByTestId(dense ? 'sidebar-dense-indicators' : 'sidebar-row-indicators');
    expect(indicators).toContainElement(screen.getByTestId('conversation-project-badge'));
    expect(screen.getByRole('link')).not.toContainElement(indicators);
    expect(screen.getByRole('img')).toHaveAttribute('src', '/api/v1/images/avatar?conversation_id=conversation-1');
  });
});
