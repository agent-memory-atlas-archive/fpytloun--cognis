// Installed at document start by the native test, before actual app bootstrap.
// No platform flags, application callbacks, private fields or ready state fakes.
import type { ChatSnapshot, ChatRealtimeFrame, MessageTimelineItem, ToolCallTimelineItem } from '$lib/chat-v2/types';

if (location.hostname !== 'window-drag.acceptance.invalid') throw Error('Synthetic origin required');
const writes: Record<string, number> = {};
const setItem = Storage.prototype.setItem;
Storage.prototype.setItem = function(key, value) {
  writes[key] = (writes[key] ?? 0) + 1;
  return setItem.call(this, key, value);
};
Object.assign(window, { nativeDragServices: {
  writes: () => ({ ...writes }),
} });

const conversation = (id: string) => ({
  conversation_id: id, agent_id: 'drag-agent', title: `Synthetic ${id}`,
  active_session_id: `session-${id}`, status: 'active', context: { type: 'web' },
});
window.fetch = async (input) => {
  const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
  if (url.origin !== location.origin || !url.pathname.startsWith('/api/')) throw Error('Unexpected fixture fetch');
  const path = url.pathname;
  const id = path.match(/\/conversations\/(drag-chat-[0-4])/)?.[1] ?? 'drag-chat-0';
  let body: unknown = {};
  if (path.endsWith('/auth/me')) body = { email: 'fixture@window-drag.acceptance.invalid', role: 'user' };
  else if (path.endsWith('/snapshot')) {
    const tool: ToolCallTimelineItem = {
      id: `tool:${id}-detail`, kind: 'tool_call', call_id: `${id}-detail`, tool_name: 'read',
      sort_key: '0000:000000000000121:000000:02:000000000', source_refs: [],
      stable: true, status: 'complete', arguments: { file_path: 'synthetic-drag-detail.txt' },
      result_preview: 'Synthetic native expanded detail.', is_error: false,
      attachments: [], file_diffs: [], truncated: false, has_full_output: false,
    };
    body = {
      schema_version: 2, projection_version: 'native-drag',
      scope: { key: `conversation:${id}`, kind: 'conversation', conversation_id: id },
      conversation: conversation(id),
      timeline: { items: [
        ...Array.from({ length: 120 }, (_, index) => ({
          id: `message:${id}-${index}`, kind: 'message', role: index % 2 ? 'assistant' : 'user',
          sort_key: `0000:${String(index + 1).padStart(15, '0')}:000000:02:000000000`,
          source_refs: [{ store: 'intaris', session_id: `session-${id}`, seq: index + 1, event_type: 'assistant_message' }],
          stable: true, message_id: `${id}-${index}`, attachments: [], partial: false,
          content: `Synthetic message ${index}\n\n` + 'Substantial **markdown** and `code`.\n\n'.repeat(8),
        } satisfies MessageTimelineItem)), tool,
      ], has_more_before: false, before_cursor: null },
      state: { state_version: 1, snapshot_generated_at: '2026-10-20T08:00:00Z',
        capabilities: [], active_turn: {}, pending: {},
        active_session: { session_id: `session-${id}`, status: 'active', todos: [] } },
      queue: { messages: [], queued_count: 0 },
      runtime: { runtime_epoch: 'native-drag', runtime_revision: 1,
        generated_at: '2026-10-20T08:00:00Z', has_active_turn: false, volatile_items: [] },
      cursor: `cursor:${id}`, server_time: '2026-10-20T08:00:00Z',
    } satisfies ChatSnapshot;
  } else if (/\/conversations\/drag-chat-[0-4]$/.test(path)) body = conversation(id);
  else if (path.includes('/sidebar')) body = { background_work: { items: [] }, agent_direct_chats: [] };
  else if (path.includes('/inbox')) body = { items: [], total: 0, unread_count: 0 };
  else if (['/sessions', '/models', '/interactions', '/todos', '/notifications', '/agents'].some((suffix) => path.endsWith(suffix))) body = [];
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
};

class FixtureSocket extends EventTarget {
  static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
  readyState = 0;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: Event) => void) | null = null;
  private timer: ReturnType<typeof setInterval> | undefined;
  private revision = 1;
  constructor() {
    super();
    queueMicrotask(() => {
      this.readyState = 1; this.onopen?.(new Event('open'));
      this.receive({ type: 'authenticated' });
    });
  }
  private receive(value: unknown) { this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(value) })); }
  send(raw: string) {
    const value = JSON.parse(raw);
    if (value.type === 'ping') this.receive({ type: 'pong' });
    if (value.type === 'chat_v2_subscribe' && value.scope?.conversation_id === 'drag-chat-4'
        && new URLSearchParams(location.search).get('streaming') === '1' && !this.timer) {
      this.timer = setInterval(() => {
        // Only the fifth chat receives fixture service stream frames.
        const id = 'drag-chat-4';
        this.receive({
          type: 'chat_v2_frame', schema_version: 2, projection_version: 'native-drag',
          scope: { key: `conversation:${id}`, kind: 'conversation', conversation_id: id },
          conversation_id: id, cursor_before: `cursor:${id}`, cursor_after: `cursor:${id}`,
          ops: [], server_time: '2026-10-20T08:00:00Z',
          runtime: { runtime_epoch: 'native-drag', runtime_revision: ++this.revision,
            generated_at: '2026-10-20T08:00:00Z', has_active_turn: true,
            active_turn: null, cycle_states: [], volatile_items: [{
              id: 'native-drag-stream', kind: 'message', role: 'assistant', stable: false, partial: true,
              sort_key: '0000:000000000000122:000000:02:000000000',
              content: `Native streaming token ${this.revision}`, message_id: 'native-drag-stream',
              attachments: [], source_refs: [],
            }] },
        } satisfies ChatRealtimeFrame);
      }, 80);
    }
  }
  close() { clearInterval(this.timer); this.readyState = 3; this.onclose?.(new Event('close')); }
}
// Replace only the service transport; native identity comes from BundleWebView.
Object.assign(window, { WebSocket: FixtureSocket });
