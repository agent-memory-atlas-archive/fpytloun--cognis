import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { HandoffTimelineItem } from '$lib/chat-v2/types';
import HandoffCard from './HandoffCard.svelte';

const item: HandoffTimelineItem = {
  id: 'handoff:sess-1:10', kind: 'handoff', sort_key: '0001:0000000010:0000:handoff',
  source_refs: [{ store: 'intaris', session_id: 'sess-1', seq: 10, event_type: 'lifecycle' }],
  stable: true, source_session_id: 'sess-1', source_seq: 9, focus: 'Review',
  text: '# Continue review\n\nPreserve **pending approval**.',
};

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('HandoffCard', () => {
  it('starts collapsed and renders Markdown only after expansion', async () => {
    const { container } = render(HandoffCard, { item });
    const toggle = screen.getByRole('button', { name: /Handoff Review/ });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByText('Continue review')).toBeNull();
    await fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(container.querySelector('strong')?.textContent).toBe('pending approval');
    await fireEvent.click(toggle);
    expect(screen.queryByText('Continue review')).toBeNull();
  });

  it('copies the entire original Markdown while collapsed', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    render(HandoffCard, { item });
    await fireEvent.click(screen.getByRole('button', { name: 'Copy handoff' }));
    expect(writeText).toHaveBeenCalledExactlyOnceWith(item.text);
    expect(screen.getByRole('status').textContent).toBe('Copied');
  });

  it('reports a clipboard failure without losing the content', async () => {
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('Denied')) } });
    render(HandoffCard, { item });
    await fireEvent.click(screen.getByRole('button', { name: 'Copy handoff' }));
    expect(screen.getByRole('status').textContent).toContain('Copy failed');
  });

  it('opens recipient selection with the exact handoff, without submitting a message', async () => {
    const onNewConversation = vi.fn();
    render(HandoffCard, { item, onNewConversation });
    await fireEvent.click(screen.getByRole('button', { name: 'New conversation from handoff' }));
    expect(onNewConversation).toHaveBeenCalledExactlyOnceWith(item);
  });

  it('shows running immediately and transitions to a result in the same card', async () => {
    const onNewConversation = vi.fn();
    const view = render(HandoffCard, { item: { ...item, status: 'running', text: '' }, onNewConversation });
    expect(screen.getByRole('status').textContent).toContain('Preparing handoff');
    expect(screen.queryByRole('button', { name: 'Copy handoff' })).toBeNull();
    await view.rerender({ item: { ...item, status: 'complete' }, onNewConversation });
    expect(screen.queryByText('Preparing handoff…')).toBeNull();
    expect(screen.getAllByRole('region', { name: 'Conversation handoff' })).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Copy handoff' })).toBeTruthy();
  });

  it('replaces running progress with a visible failure and no result actions', async () => {
    const view = render(HandoffCard, { item: { ...item, status: 'running', text: '' } });
    await view.rerender({ item: { ...item, status: 'failed', text: '', error: 'Handoff cancelled.' } });
    expect(screen.getByRole('alert').textContent).toBe('Handoff cancelled.');
    expect(screen.queryByRole('button', { name: 'Copy handoff' })).toBeNull();
  });

  it('replaces create with the persisted recipient link only after creation', () => {
    render(HandoffCard, { item: { ...item, recipient_conversation_id: 'conv-recipient' }, onNewConversation: vi.fn() });
    expect(screen.getByRole('link', { name: 'Open handoff conversation' }).getAttribute('href')).toBe('/chat/conv-recipient');
    expect(screen.queryByRole('button', { name: 'New conversation from handoff' })).toBeNull();
  });
});
