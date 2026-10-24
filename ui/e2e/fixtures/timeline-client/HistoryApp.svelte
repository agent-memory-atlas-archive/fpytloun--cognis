<script lang="ts">
  import { onMount } from 'svelte';
  import FullChat from '../../../src/routes/(app)/chat/[conversationId]/+page.svelte';
  import ScopedChat from '$lib/components/chat-v2/ScopedChatV2Timeline.svelte';
  import { api } from '$lib/api/client';
  import { auth } from '$lib/stores/auth';
  import { DEFAULT_USER_PREFERENCES } from '$lib/user-preferences';
  import { documentCoordination } from '$lib/document-coordination';
  import { offlineCache } from '$lib/offline/cache';
  import { chatV2Api } from '$lib/chat-v2/api';
  import { wsClient } from '$lib/ws/client';
  import { acquireTimeline, timelineResourceCounts } from '$lib/chat-v2/timeline-controller.svelte';
  import { conversationTimelineScope, type ChatSnapshot, type MessageTimelineItem } from '$lib/chat-v2/types';
  import type { CognisWebSocketClientEvent } from '$lib/ws/types';
  import { page } from './state.svelte';

  const scope = conversationTimelineScope('synthetic-history');
  const conversation = {
    conversation_id: scope.conversation_id!, agent_id: 'synthetic-agent', status: 'active',
    title: 'Synthetic history', context: { type: 'web' }, has_message_history: true,
  };
  const agent = { agent_id: 'synthetic-agent', name: 'Synthetic agent', enabled: true };
  const auditPreloads = new URLSearchParams(location.search).has('audit-preloads');
  const nextConversation = { ...conversation, conversation_id: 'synthetic-next', title: 'Next conversation' };
  const row = (index: number): MessageTimelineItem => ({
    id: `history:${index}`, kind: 'message', message_id: `history:${index}`, role: 'assistant',
    sort_key: String(10_000 + index).padStart(8, '0'), source_refs: [], stable: true,
    content: `Synthetic history ${index}`, attachments: [], partial: false, status: 'complete',
  });
  const sample = (): ChatSnapshot => ({
    schema_version: 2, projection_version: 'synthetic-history', scope, conversation,
    cursor: 'synthetic:initial', server_time: '',
    timeline: { items: Array.from({ length: 200 }, (_, i) => i === 151 ? {
      ...row(i), kind: 'notice', title: 'Synthetic child hook', level: 'info',
      hook: { run_id: 'synthetic-hook-run', hook_id: 'synthetic-hook',
        status: 'completed', child_session_id: 'synthetic-child-session', trigger: 'conversation_idle' },
    } : row(i)), has_more_before: true, before_cursor: 'older:1' },
    state: { state_version: 1, active_turn: {}, pending: {}, active_session: {}, capabilities: [] },
    runtime: null, queue: { messages: [], queued_count: 0 },
  } as ChatSnapshot);
  let ready = $state(false);
  let scopedVisible = $state(!new URLSearchParams(location.search).has('full-only'));
  let fullVisible = $state(true);
  let failure = $state('');

  onMount(() => {
    void (async () => {
      // Fictional coordination metadata, not a credential or auth session.
      // The real principal-scoped registry/cache and fences stay active.
      await documentCoordination().initialize();
      await documentCoordination().verified('history-fixture@cognis.test');
      await offlineCache.setOwner(documentCoordination().storageName('offline-cache'));
      const listeners = new Set<(event: CognisWebSocketClientEvent) => void>();
      wsClient.subscribe = callback => { listeners.add(callback); return () => { listeners.delete(callback); }; };
      wsClient.acquireChatV2 = () => {};
      wsClient.releaseChatV2 = () => {};
      wsClient.updateChatV2Cursor = () => {};
      wsClient.subscribeConversation = () => {};
      wsClient.unsubscribeConversation = () => {};
      const state = {
        snapshots: 0, nextSnapshots: 0, historyRequests: 0, appends: 0, unexpectedRequests: [] as string[],
        snapshotAborts: 0,
        releaseSnapshot: null as (() => void) | null,
        syncRequests: 0,
        releaseSync: null as (() => void) | null,
        preloadNext: () => {
          for (const listener of listeners) listener({
            type: 'conversation_updated', conversation_id: nextConversation.conversation_id, has_active_turn: true,
          } as CognisWebSocketClientEvent);
        },
        releaseHistory: null as (() => void) | null,
        counts: () => timelineResourceCounts(),
        owner: () => offlineCache.currentOwner,
        closeScoped: () => { scopedVisible = false; },
        closeFull: () => { fullVisible = false; },
        reopenFull: () => { fullVisible = true; },
        changeConversation: () => {
          page.params.conversationId = 'synthetic-next';
          page.url = new URL('http://localhost/chat/synthetic-next');
        },
        returnConversation: () => {
          page.params.conversationId = scope.conversation_id!;
          page.url = new URL(`http://localhost/chat/${scope.conversation_id}`);
        },
        append: () => {
          const lease = acquireTimeline(scope);
          const cursor = lease.controller.store.snapshot.cursor!;
          state.appends++;
          const event = {
            type: 'chat_v2_frame', schema_version: 2, projection_version: 'synthetic-history', scope,
            conversation_id: scope.conversation_id, cursor_before: cursor,
            cursor_after: `synthetic:live:${state.appends}`,
            ops: [{ op: 'upsert_item', item: row(200 + state.appends) },
              { op: 'upsert_item', item: { ...row(150), content: `Synthetic live update ${state.appends}` } }],
            runtime: null, server_time: '',
          } as CognisWebSocketClientEvent;
          for (const listener of listeners) listener(event);
          lease.release();
        },
        older: () => {
          const lease = acquireTimeline(scope);
          const before = lease.controller.store.snapshot.beforeCursor!;
          return lease.controller.older(before).finally(lease.release);
        },
      };
      Object.assign(window, { historyFixture: state });
      window.fetch = async input => {
        if (String(input) === '/api/readyz') return Response.json({ status: 'ready' });
        if (auditPreloads && String(input) === '/api/auth/me') {
          return Response.json({ email: 'history-fixture@cognis.test', role: 'user' });
        }
        state.unexpectedRequests.push(String(input));
        throw new Error(`Unexpected nonfixture request: ${input}`);
      };
      Object.assign(api.conversations, {
        detail: async id => ({ ...conversation, conversation_id: id }), sessions: async () => [],
        sidebar: async () => ({
          conversations: { items: auditPreloads ? [conversation, nextConversation] : [conversation], cursor: null, has_more: false },
          agents: [agent], agent_direct_chats: [], context_types: ['web'], sidebar_revision: '1', is_delta: false,
          sync_timestamp: '2026-10-19T16:00:00Z',
          background_work: { items: [], active_count: 0, truncated: false, generated_at: '2026-10-19T16:00:00Z' },
        }),
        contextTypes: async () => ['web'], waiting: async () => [],
        getQueue: async () => ({ messages: [], queued_count: 0 }),
        markRead: async () => {}, rememberOpened: async () => {},
      });
      Object.assign(api.agents, { list: async () => [agent] });
      Object.assign(api.sessions, { detail: async () => ({
        session_id: 'synthetic-child-session', conversation_id: scope.conversation_id,
        agent_id: agent.agent_id, status: 'completed', kind: 'child',
      }) });
      Object.assign(api.projects, { list: async () => [] });
      Object.assign(api.notifications, { list: async () => [] });
      Object.assign(api.search, { health: async () => ({ enabled: false }) });
      Object.assign(api.userPreferences, { get: async () => DEFAULT_USER_PREFERENCES });
      chatV2Api.clientPerformance = async () => {};
      chatV2Api.snapshot = async (asked, options: { signal?: AbortSignal } = {}) => {
        if (typeof asked !== 'string' && asked.conversation_id === 'synthetic-next') {
          state.nextSnapshots++;
          return {
            ...sample(), scope: asked, conversation: { ...conversation, conversation_id: 'synthetic-next' },
            timeline: { items: [{ ...row(1), id: 'next:1', message_id: 'next:1', content: 'New conversation only' }],
              has_more_before: false, before_cursor: null },
          } as ChatSnapshot;
        }
        if (typeof asked !== 'string' && asked.key !== scope.key) return {
          ...sample(), scope: asked,
          timeline: { items: [], has_more_before: false, before_cursor: null },
        };
        state.snapshots++;
        if (new URLSearchParams(location.search).has('hold-snapshot') && state.snapshots === 1) {
          await new Promise<void>((resolve, reject) => {
            const aborted = () => {
              state.snapshotAborts++;
              reject(options.signal?.reason ?? new DOMException('The operation was aborted.', 'AbortError'));
            };
            options.signal?.addEventListener('abort', aborted, { once: true });
            state.releaseSnapshot = () => {
              options.signal?.removeEventListener('abort', aborted);
              resolve();
            };
            if (options.signal?.aborted) aborted();
          });
        }
        return sample();
      };
      chatV2Api.sync = async (asked, cursor) => {
        state.syncRequests++;
        if (new URLSearchParams(location.search).has('hold-sync') && state.syncRequests === 1) {
          await new Promise<void>(resolve => { state.releaseSync = resolve; });
        }
        return {
        schema_version: 2, projection_version: 'synthetic-history',
        scope: typeof asked === 'string' ? conversationTimelineScope(asked) : asked,
        conversation_id: typeof asked === 'string' ? asked : asked.conversation_id!,
        cursor_before: cursor, cursor_after: cursor, ops: [], has_more: false, runtime: null,
        reset_required: false, server_time: '',
        };
      };
      chatV2Api.timeline = async (_scope, options) => {
        state.historyRequests++;
        const page = Number(options?.before?.split(':')[1]);
        if (page !== state.historyRequests || page > 2) throw new Error('Synthetic history cursor did not advance');
        await new Promise<void>(resolve => { state.releaseHistory = resolve; });
        state.releaseHistory = null;
        return {
          schema_version: 2, projection_version: 'synthetic-history', scope, conversation_id: scope.conversation_id!,
          items: Array.from({ length: 60 }, (_, i) => row(i - page * 60)),
          has_more_before: page < 2, before_cursor: page < 2 ? 'older:2' : null, server_time: '',
        };
      };
      if (auditPreloads) await auth.bootstrap();
      ready = true;
    })().catch(error => { failure = String(error); });
  });
</script>

{#if failure}<p role="alert">{failure}</p>{/if}
{#if ready}
  <div class="flex h-dvh min-h-0 flex-col bg-slate-950 text-slate-200">
    <section class="relative flex min-h-0 flex-1 flex-col" data-testid="full-surface">
      {#if fullVisible}<FullChat />{/if}
    </section>
    <section class="relative flex h-56 min-h-0 shrink-0 flex-col border-t" data-testid="scoped-surface">
      {#if scopedVisible}<ScopedChat {scope} autoBackfill={false} compact hasEditableComposer />{/if}
    </section>
  </div>
{/if}
