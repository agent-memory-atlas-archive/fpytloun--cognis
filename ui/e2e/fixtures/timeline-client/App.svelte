<script lang="ts">
  import { onMount } from 'svelte';
  import Workspace from '$lib/components/dashboard/ConversationModalWorkspace.svelte';
  import Compact from '$lib/components/chat-v2/CompactConversationChat.svelte';
  import { offlineCache } from '$lib/offline/cache';
  import { documentCoordination } from '$lib/document-coordination';
  import { acquireTimeline } from '$lib/chat-v2/timeline-controller.svelte';
  import { conversationTimelineScope, type ChatSnapshot } from '$lib/chat-v2/types';
  import { wsClient } from '$lib/ws/client';
  import { ChatV2ApiClient, chatV2Api } from '$lib/chat-v2/api';

  let ready = $state(false);
  let failure = $state('');
  let surface = $state('dashboard');
  const id = 'synthetic-mobile-diagnostic';
  const scope = conversationTimelineScope(id);
  const sample = (): ChatSnapshot => ({
    schema_version: 2, projection_version: 'diagnostic', scope,
    cursor: 'synthetic:1', server_time: '',
    conversation: { conversation_id: id, agent_id: 'synthetic-agent', status: 'active', has_message_history: true },
    timeline: { items: [{
      id: 'synthetic-row', kind: 'message', role: 'assistant', message_id: 'synthetic-row',
      content: 'Synthetic timeline ready', sort_key: '0001', source_refs: [], stable: true,
      status: 'complete', attachments: [], partial: false,
    }], before_cursor: null, has_more_before: false },
    state: { state_version: 1, snapshot_generated_at: '', capabilities: [], active_turn: {}, pending: {}, active_session: {} },
    queue: { messages: [], queued_count: 0 }, runtime: null,
  } as unknown as ChatSnapshot);

  onMount(() => {
    void (async () => {
      const params = new URL(location.href).searchParams;
      surface = params.get('surface') ?? 'dashboard';
      const mode = params.get('mode') ?? 'normal';
      const pending = params.get('pending') ?? 'delay';
      const events: Array<{ event: string; ms: number }> = [];
      const start = performance.now();
      const record = (event: string) => events.push({ event, ms: Math.round(performance.now() - start) });
      let releasePending!: () => void;
      const pendingGate = new Promise<void>(resolve => { releasePending = resolve; });
      const state = { events, subscriptions: 0, acquired: 0, released: 0, snapshot: 0, sync: 0, pendingCancelled: 0, releasePending,
        invalidateOwner: () => { void offlineCache.setOwner('changed-synthetic-owner'); record('owner-changed'); },
        close: () => { ready = false; record('close'); } };
      Object.assign(window, { diagnostic: state });
      const subscribe = wsClient.subscribe.bind(wsClient);
      wsClient.subscribe = callback => {
        state.subscriptions += 1;
        const unsubscribe = subscribe(callback);
        return () => { state.subscriptions -= 1; unsubscribe(); };
      };
      wsClient.acquireChatV2 = () => { state.acquired += 1; record('ws-acquire'); };
      wsClient.releaseChatV2 = () => { state.released += 1; };

      // Synthetic fixture contract only: local coordination metadata for a
      // fictional test principal, no credentials/cookies/auth endpoint/session.
      // Production lease validation and account fences remain in operation.
      const coordination = documentCoordination();
      await coordination.initialize();
      await coordination.verified('mobile-diagnostic@cognis.test');
      await offlineCache.setOwner(coordination.storageName('offline-cache'));
      const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
        status, headers: { 'Content-Type': 'application/json' },
      });
      const delay = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));
      window.fetch = async (input, init) => {
        const url = String(input);
        record(`fetch:${url}`);
        if (url.includes('/conversations/sidebar')) return json({ items: [], has_more: false });
        // Keep the local outage synthetic; never let reachability probes escape
        // into an HTTP backend or manufacture a healthy reconnect/retry loop.
        if (url.includes('/readyz')) return json({}, 503);
        if (url.includes('/notifications')) {
          if (pending === 'body' || pending === 'error-body') return new Response(new ReadableStream({
            cancel() { state.pendingCancelled += 1; record('pending-body-cancelled'); },
          }), {
            status: pending === 'error-body' ? 503 : 200, headers: { 'Content-Type': 'application/json' },
          });
          await pendingGate;
          record('pending-settled');
          return pending === 'fail' ? json({ detail: 'Synthetic pending failure' }, 500) : json([]);
        }
        if (url.includes('/snapshot')) {
          state.snapshot += 1;
          if (mode === 'network') return new Promise((_, reject) => {
            init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true });
          });
          await delay(1100);
          record('snapshot-response');
          return json(sample());
        }
        if (url.includes('/sync')) {
          state.sync += 1;
          return json({
            schema_version: 2, projection_version: 'diagnostic', scope, conversation_id: id,
            cursor_before: 'synthetic:1', cursor_after: 'synthetic:1', ops: [], has_more: false,
            reset_required: false, server_time: '', runtime: null,
          });
        }
        if (url.includes('/sessions')) return json([]);
        if (url.includes('/work')) return json({ items: [], has_more: false, mutations: [], commands: [], artifacts: [], summary: {} });
        throw new Error(`Unexpected fixture request: ${url}`);
      };
      // ChatV2ApiClient intentionally captures its fetch implementation in the
      // constructor. Use its public transport injection, not a private field.
      const client = new ChatV2ApiClient({ fetch: window.fetch });
      chatV2Api.snapshot = client.snapshot.bind(client);
      chatV2Api.sync = client.sync.bind(client);
      chatV2Api.timeline = client.timeline.bind(client);
      chatV2Api.work = client.work.bind(client);
      if (mode === 'warm') {
        const warm = acquireTimeline(scope);
        warm.controller.store.replaceFromSnapshot(sample());
        warm.release();
        record('normal-chat-warm-store');
      }
      if (mode === 'blocked-cache' || mode === 'owner-change') {
        offlineCache.get = (kind, key, owner) => {
          record(`cache:${kind}`);
          return new Promise(() => {});
        };
      }
      if (mode === 'blocked-idb' || mode === 'missing-idb') {
        const open = indexedDB.open.bind(indexedDB);
        indexedDB.open = ((name: string, version?: number) => {
          record(`idb-open:${name}`);
          if (mode === 'missing-idb') throw new DOMException('Synthetic unavailable IDB', 'InvalidStateError');
          if (name.startsWith('cognis-offline')) return {} as IDBOpenDBRequest;
          return open(name, version);
        }) as typeof indexedDB.open;
      }
      if (mode === 'coordination') {
        coordination.synchronize = () => new Promise(() => {});
      }
      record('mount');
      ready = true;
    })().catch(error => { failure = String(error); });
  });
</script>

<main class="flex h-dvh min-h-0 flex-col bg-slate-950 text-slate-200">
  <header class="border-b border-slate-700 p-4">Synthetic mobile conversation <span>ACTIVE</span></header>
  {#if failure}<p role="alert">{failure}</p>{/if}
  {#if ready}
    <div class="flex min-h-0 flex-1 flex-col">
      {#if surface === 'dashboard'}
        <Workspace conversationId={id} inspectorOpen={false} />
      {:else}
        <Compact conversationId={id} embedded />
      {/if}
    </div>
  {/if}
</main>
