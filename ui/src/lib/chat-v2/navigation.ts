import { getContext, setContext } from 'svelte';
import { chatV2Api } from './api';
import { addToast } from '$lib/stores/toasts';
import { conversationTimelineScope, type TimelineScope, type WorkstreamRef } from './types';

const NAVIGATION = Symbol('chat-navigation');
export interface ChatNavigation {
  openConversation(conversationId: string): Promise<void>;
}

/** Cards and work trees enter the same session navigator in every host. */
export function provideChatNavigation(
  currentScope: () => TimelineScope,
  openSession: (sessionId: string, node: WorkstreamRef) => void | Promise<void>,
): void {
  setContext<ChatNavigation>(NAVIGATION, {
    async openConversation(conversationId) {
      const parent = currentScope();
      const overview = await chatV2Api.activityOverview(conversationTimelineScope(conversationId));
      if (currentScope().key !== parent.key) return;
      const root = overview.workstreams.find(node => node.key === node.root_key);
      if (!root) throw new Error('Conversation session is not available yet. Retry opening it.');
      await openSession(root.session_id, {
        ...root,
        kind: 'managed',
        conversation_id: conversationId,
        root_key: parent.key,
        parent_key: parent.key,
      });
    },
  });
}

export function chatNavigation(): ChatNavigation | undefined {
  return getContext<ChatNavigation | undefined>(NAVIGATION);
}

export function isPlainNavigation(event: MouseEvent): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

export function followConversationLink(event: MouseEvent, conversationId: string, navigation: ChatNavigation | undefined): void {
  if (!navigation || !isPlainNavigation(event)) return;
  event.preventDefault();
  void navigation.openConversation(conversationId).catch(error => {
    addToast(error instanceof Error ? error.message : 'Could not open conversation.', 'error');
  });
}
