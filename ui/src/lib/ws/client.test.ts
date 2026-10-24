import { afterEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

vi.mock('$lib/config', () => ({
  getWebSocketUrl: () => 'ws://localhost/api/ws'
}));

vi.mock('$lib/stores/auth', () => ({
  auth: {
    getSnapshot: () => ({ status: 'authenticated', initialized: true, user: { email: 'user@example.com' } }),
    clear: vi.fn()
  }
}));

vi.mock('$lib/errors', () => ({
  reportError: vi.fn()
}));

import { CognisWebSocketClient, isMetadataRefreshOnlyScope } from './client';
import { metadataReadFlights } from '$lib/api/read-flights';
import { conversationTimelineScope, sessionTimelineScope, taskStepTimelineScope, type ChatRealtimeFrame } from '$lib/chat-v2/types';

it('requires an explicit server proof for routine chat/sidebar changes and stays fail-closed otherwise', () => {
  for (const reason of ['chat_scope_changed', 'sidebar_changed']) {
    expect(isMetadataRefreshOnlyScope(reason, true)).toBe(true);
    for (const marker of [undefined, false, 'true', 1]) {
      expect(isMetadataRefreshOnlyScope(reason, marker)).toBe(false);
    }
  }
  expect(isMetadataRefreshOnlyScope('permission_revoked', true)).toBe(false);
});

function frame(conversationId: string, cursor: string): ChatRealtimeFrame {
  return {
    type: 'chat_v2_frame',
    conversation_id: conversationId,
    schema_version: 2,
    projection_version: 'test',
    cursor_before: cursor,
    cursor_after: `${cursor}:next`,
    ops: [],
    cycle_states: [],
    runtime: null,
    server_time: '2026-07-07T00:00:00Z',
  };
}

describe('CognisWebSocketClient', () => {
  it('does not invalidate metadata for heartbeats but fences relevant invalidations before consumers', () => {
    const invalidate = vi.spyOn(metadataReadFlights, 'invalidate');
    const client = new CognisWebSocketClient();
    const handleMessage = (client as unknown as { handleMessage(raw: string): void }).handleMessage.bind(client);
    const listener = vi.fn(() => expect(invalidate).toHaveBeenCalledTimes(1));
    handleMessage(JSON.stringify({ type: 'pong' }));
    handleMessage(JSON.stringify({ type: 'pong' }));
    expect(invalidate).not.toHaveBeenCalled();
    const stop = client.subscribe(listener);
    handleMessage(JSON.stringify({ type: 'scope_invalidated', reason: 'sidebar_changed' }));
    expect(listener).toHaveBeenCalledTimes(1);
    stop();
    client.disconnect();
  });

  it('delivers routine refreshes without cancelling metadata reads, but fences access and reconnect events', () => {
    const invalidate = vi.spyOn(metadataReadFlights, 'invalidate');
    const client = new CognisWebSocketClient();
    const handleMessage = (client as unknown as { handleMessage(raw: string): void }).handleMessage.bind(client);
    const listener = vi.fn();
    const stop = client.subscribe(listener);
    for (const type of [
      'message_complete', 'turn_started', 'turn_settled', 'queued',
      'queued_messages_updated', 'conversation_runtime_snapshot', 'conversation_state_delta',
    ]) handleMessage(JSON.stringify({ type }));
    for (const reason of [
      'executor_state_changed', 'notification_state_changed',
      'task_progress_changed', 'schedule_action_changed',
    ]) handleMessage(JSON.stringify({ type: 'scope_invalidated', reason }));
    expect(listener).toHaveBeenCalledTimes(11);
    expect(invalidate).not.toHaveBeenCalled();
    for (const event of [
      { type: 'scope_invalidated', reason: 'sidebar_changed' },
      { type: 'scope_invalidated', reason: 'chat_scope_changed' },
      { type: 'scope_invalidated', reason: 'future_access_change' },
      { type: 'sidebar_conversation_removed', conversation_id: 'shared-conversation' },
      { type: 'reconnected' },
    ]) handleMessage(JSON.stringify(event));
    expect(invalidate).toHaveBeenCalledTimes(5);
    stop();
    client.disconnect();
  });

  it('reference-counts executor monitoring, resubscribes after auth and releases idempotently', () => {
    vi.useFakeTimers();
    const socket = { readyState: WebSocket.OPEN, send: vi.fn(), close: vi.fn() } as unknown as WebSocket;
    const client = new CognisWebSocketClient();
    const internals = client as unknown as { socket: WebSocket; handleMessage(raw: string): void };
    internals.socket = socket;
    const first = client.acquireExecutorMonitor();
    const second = client.acquireExecutorMonitor();
    expect(socket.send).not.toHaveBeenCalled();
    internals.handleMessage(JSON.stringify({ type: 'authenticated' }));
    expect(socket.send).toHaveBeenLastCalledWith(JSON.stringify({ type: 'executor_monitor_subscribe' }));
    expect(socket.send).toHaveBeenCalledTimes(1);
    internals.handleMessage(JSON.stringify({ type: 'authenticated' }));
    expect(socket.send).toHaveBeenCalledTimes(2);
    first();
    first();
    expect(socket.send).toHaveBeenCalledTimes(2);
    second();
    second();
    expect(socket.send).toHaveBeenLastCalledWith(JSON.stringify({ type: 'executor_monitor_unsubscribe' }));
    expect(socket.send).toHaveBeenCalledTimes(3);
    internals.handleMessage(JSON.stringify({ type: 'authenticated' }));
    expect(socket.send).toHaveBeenCalledTimes(3);
    client.disconnect();
    expect(vi.getTimerCount()).toBe(0);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('keeps streaming in order when animation frames stop running', () => {
    vi.useFakeTimers();
    vi.spyOn(window, 'requestAnimationFrame').mockReturnValue(1);
    const cancel = vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
    const client = new CognisWebSocketClient();
    const received: string[] = [];
    client.subscribe((event) => {
      if (event.type === 'chat_v2_frame') received.push(event.cursor_before!);
    });
    const handleMessage = (client as unknown as { handleMessage(raw: string): void }).handleMessage.bind(client);

    handleMessage(JSON.stringify(frame('conv', 'first')));
    vi.advanceTimersByTime(50);
    handleMessage(JSON.stringify(frame('conv', 'second')));
    vi.advanceTimersByTime(50);
    expect(received).toEqual(['first', 'second']);
    expect(cancel).toHaveBeenCalled();

    handleMessage(JSON.stringify(frame('conv', 'third')));
    vi.advanceTimersByTime(100);
    expect(received).toEqual(['first', 'second', 'third']);
    client.disconnect();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('cancels the fallback after a normal animation-frame flush or unsubscribe', () => {
    vi.useFakeTimers();
    const callbacks: FrameRequestCallback[] = [];
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      callbacks.push(callback);
      return callbacks.length;
    });
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
    const client = new CognisWebSocketClient();
    const received = vi.fn();
    client.subscribe(received);
    const handleMessage = (client as unknown as { handleMessage(raw: string): void }).handleMessage.bind(client);

    handleMessage(JSON.stringify(frame('conv', 'first')));
    callbacks[0](0);
    vi.advanceTimersByTime(100);
    expect(received).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);

    handleMessage(JSON.stringify(frame('conv', 'second')));
    client.unsubscribeConversation('conv');
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(100);
    expect(received).toHaveBeenCalledTimes(1);
    client.disconnect();
  });

  it('drops queued Chat v2 frames for an unsubscribed conversation before flush', () => {
    const callbacks: FrameRequestCallback[] = [];
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      callbacks.push(callback);
      return callbacks.length;
    });
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
    const client = new CognisWebSocketClient();
    const received: string[] = [];
    client.subscribe((event) => {
      if (event.type === 'chat_v2_frame') {
        received.push(event.conversation_id);
      }
    });
    const handleMessage = (client as unknown as { handleMessage(raw: string): void }).handleMessage.bind(client);

    handleMessage(JSON.stringify(frame('source-conv', 'cursor-1')));
    handleMessage(JSON.stringify(frame('target-conv', 'cursor-2')));
    client.unsubscribeConversation('source-conv');

    callbacks[0]?.(0);

    expect(received).toEqual(['target-conv']);
  });

  it('re-subscribes exact conversation, session, and task-step cursors through Chat v2', () => {
    class TestWebSocket {
      static OPEN = 1;
      static CONNECTING = 0;
      static instances: TestWebSocket[] = [];
      readyState = TestWebSocket.OPEN;
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      sent: string[] = [];
      close = vi.fn();
      constructor() {
        TestWebSocket.instances.push(this);
      }
      send(payload: string): void {
        this.sent.push(payload);
      }
    }
    vi.stubGlobal('WebSocket', TestWebSocket);
    const client = new CognisWebSocketClient();
    const conversation = conversationTimelineScope('conv-1');
    const session = sessionTimelineScope('session-1', 'conv-1');
    const taskStep = taskStepTimelineScope('task-1', 'step-1', 'conv-1');
    client.subscribeConversation('conv-1', 4, 'session-1');
    client.acquireChatV2(conversation, 'conversation-cursor');
    client.acquireChatV2(session, 'session-cursor');
    client.acquireChatV2(taskStep, 'task-cursor');
    client.updateChatV2Cursor(conversation, 'conversation-cursor-2');
    client.updateChatV2Cursor(session, 'session-cursor-2');
    client.updateChatV2Cursor(taskStep, 'task-cursor-2');

    const firstSocket = TestWebSocket.instances[0];
    expect(firstSocket).toBeDefined();
    const authenticate = (socket: TestWebSocket): void => {
      socket.onmessage?.(
        { data: JSON.stringify({ type: 'authenticated' }) } as MessageEvent<string>
      );
    };
    authenticate(firstSocket);
    client.disconnect();
    client.reAuthenticate();
    const secondSocket = TestWebSocket.instances[1];
    expect(secondSocket).toBeDefined();
    authenticate(secondSocket);

    expect(secondSocket.sent.map((payload) => JSON.parse(payload))).toEqual([
      { type: 'chat_v2_subscribe', scope: conversation, cursor: 'conversation-cursor-2', catch_up: true },
      { type: 'chat_v2_subscribe', scope: session, cursor: 'session-cursor-2' },
      { type: 'chat_v2_subscribe', scope: taskStep, cursor: 'task-cursor-2' }
    ]);
    client.disconnect();
  });

  it('ignores a stale socket close after replacement authentication', () => {
    class TestWebSocket {
      static OPEN = 1;
      static CONNECTING = 0;
      static instances: TestWebSocket[] = [];
      readyState = TestWebSocket.OPEN;
      onopen: (() => void) | null = null;
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      onerror: (() => void) | null = null;
      onclose: ((event: CloseEvent) => void) | null = null;
      sent: string[] = [];
      close = vi.fn();
      constructor() {
        TestWebSocket.instances.push(this);
      }
      send(payload: string): void {
        this.sent.push(payload);
      }
    }
    vi.stubGlobal('WebSocket', TestWebSocket);

    const client = new CognisWebSocketClient();
    client.subscribeConversation('conv-1', 7, 'session-1');
    const firstSocket = TestWebSocket.instances[0];
    expect(firstSocket).toBeDefined();
    firstSocket.onmessage?.({ data: JSON.stringify({ type: 'authenticated' }) } as MessageEvent<string>);

    client.reAuthenticate();
    const secondSocket = TestWebSocket.instances[1];
    expect(secondSocket).toBeDefined();
    secondSocket.onmessage?.({ data: JSON.stringify({ type: 'authenticated' }) } as MessageEvent<string>);

    firstSocket.onclose?.({ code: 1006 } as CloseEvent);

    expect(get(client.state).status).toBe('connected');
    expect(secondSocket.sent.map((payload) => JSON.parse(payload))).toEqual([]);
    expect(firstSocket.close).toHaveBeenCalledOnce();
    expect(secondSocket.close).not.toHaveBeenCalled();
    client.disconnect();
  });
});
