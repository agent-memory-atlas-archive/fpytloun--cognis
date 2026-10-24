import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ChatMessage from './ChatMessage.svelte';
import { forkAssistantMessageContext } from '$lib/chat-message-actions';
import type { MessageTimelineItem } from '$lib/timeline-render-model';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('single-click message fork', () => {
  it('forks immediately without a native dialog and blocks repeat clicks while pending', async () => {
    let finishFork!: () => void;
    const fork = vi.fn(() => new Promise<void>((resolve) => { finishFork = resolve; }));
    const confirmation = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const item: MessageTimelineItem = {
      id: 'message-review', kind: 'message', sessionId: 'sess_review',
      role: 'assistant', content: 'Reviewed', html: '<p>Reviewed</p>', seq: 42, timestamp: null,
    };
    render(ChatMessage, {
      props: { item },
      context: new Map([[forkAssistantMessageContext, fork]]),
    });
    const button = screen.getByRole('button', { name: 'Fork conversation from this message' });
    await fireEvent.click(button);
    expect(confirmation).not.toHaveBeenCalled();
    expect(fork).toHaveBeenCalledExactlyOnceWith('sess_review', 42);
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
    expect(button).toHaveAccessibleName('Forking conversation…');
    await fireEvent.click(button);
    expect(fork).toHaveBeenCalledTimes(1);

    finishFork();
    await waitFor(() => expect(button).toBeEnabled());
    expect(button).toHaveAttribute('aria-busy', 'false');
    expect(button).toHaveAccessibleName('Fork conversation from this message');
  });
});
