import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';
import { DEFAULT_USER_PREFERENCES } from '$lib/user-preferences';
import type { UserPreferences } from '$lib/types/api';
import type { ChatRealtimeFrame, ChatSnapshot, TimelineItem, TimelineScope, ToolCallTimelineItem } from '$lib/chat-v2/types';
import ScopedChatV2Timeline from './ScopedChatV2Timeline.svelte';
import ChatV2Composer from './ChatV2Composer.svelte';

vi.mock('$lib/stores/userPreferences', async () => {
  const { writable } = await import('svelte/store');
  const { DEFAULT_USER_PREFERENCES } = await import('$lib/user-preferences');
  return { userPreferences: writable(structuredClone(DEFAULT_USER_PREFERENCES)) };
});
import { userPreferences } from '$lib/stores/userPreferences';
const preferences = userPreferences as ReturnType<typeof writable<UserPreferences>>;
beforeAll(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
});
const scope: TimelineScope = { key: 'conversation:settings-parity', kind: 'conversation', conversation_id: 'settings-parity' };
const base = { source_refs: [], stable: true, turn_id: 'settings-turn', turn_cycle_index: 0, assistant_phase_index: 0 };
function tool(index: number, internal = false): ToolCallTimelineItem {
  return { ...base, id: `settings-tool-${index}`, sort_key: String(index).padStart(4, '0'), kind: 'tool_call',
    call_id: `settings-call-${index}`, tool_name: internal ? 'read_tool_output' : 'bash',
    arguments: { command: 'true', description: `Command ${index}` }, is_error: index % 2 === 0,
    status: index % 2 === 0 ? 'failed' : 'complete', attachments: [], file_diffs: [],
    truncated: false, has_full_output: false };
}
const assistant: TimelineItem = { ...base, kind: 'message', id: 'settings-assistant', sort_key: '0004',
  role: 'assistant', message_id: 'settings-assistant', content: 'Intermediate **Markdown** remains readable.',
  attachments: [], partial: false };
const items: TimelineItem[] = [
  tool(1), tool(2), tool(3), assistant, tool(5), tool(6), tool(7),
  { ...base, kind: 'thinking', id: 'settings-thinking', sort_key: '0008',
    blocks: [
      { id: 'settings-thought', content: 'Visible reasoning', status: 'complete' },
      { id: 'settings-thought-next', content: 'Further reasoning', status: 'complete' },
    ] },
  tool(9, true), tool(10, true),
  { ...base, kind: 'recap', id: 'settings-recap', sort_key: '0011', text: 'Historical recap',
    source_session_id: 'settings-session', source_seq: 11, auto: true, stats_version: 2,
    file_diffs_omitted: false, scope: 'recent_window', deliverables: [], artifacts: [], files: [] },
];
function value(chat: Partial<UserPreferences['chat']> = {}): UserPreferences {
  return { ...structuredClone(DEFAULT_USER_PREFERENCES), chat: { ...DEFAULT_USER_PREFERENCES.chat, ...chat } };
}
function mount(compact: boolean, override?: UserPreferences) {
  let listener: ((frame: ChatRealtimeFrame) => void) | undefined;
  const snapshot = {
    schema_version: 2, projection_version: 'test', scope,
    conversation: { conversation_id: scope.conversation_id, agent_id: 'settings-agent', status: 'active' },
    timeline: { items, has_more_before: false, before_cursor: null },
    state: { state_version: 1, capabilities: [], active_turn: {}, pending: {}, active_session: {} },
    queue: { messages: [], queued_count: 0 },
    runtime: { runtime_epoch: 'settings-epoch', runtime_revision: 0, has_active_turn: false,
      active_turn: null, volatile_items: [], cycle_states: [] },
    cursor: 'settings-cursor', server_time: '',
  } as unknown as ChatSnapshot;
  const view = render(ScopedChatV2Timeline, {
    scope, compact, preferences: override, autoBackfill: false,
    api: { snapshot: vi.fn().mockResolvedValue(snapshot), sync: vi.fn(), timeline: vi.fn() },
    realtime: { subscribe: (next: (frame: ChatRealtimeFrame) => void) => { listener = next; return () => { listener = undefined; }; },
      acquireChatV2: () => {}, updateChatV2Cursor: () => {}, releaseChatV2: () => {} },
  });
  return Object.assign(view, { emit: (frame: ChatRealtimeFrame) => listener?.(frame) });
}
async function expand(container: HTMLElement) {
  for (const button of container.querySelectorAll<HTMLButtonElement>(
    '[data-kind="activity_segment"] > button[aria-expanded="false"], [data-kind="tool_group"] > button[aria-expanded="false"]',
  )) await fireEvent.click(button);
}
afterEach(() => { cleanup(); preferences.set(value()); });

describe.each([false, true])('reactive chat preferences (compact=%s)', (compact) => {
  it('preserves order, failures, Markdown and manual expansion while changing grouping/separation live', async () => {
    preferences.set(value());
    const view = mount(compact);
    await waitFor(() => expect(view.container.querySelector('[data-kind="activity_segment"]')).not.toBeNull());
    await expand(view.container);
    expect(view.container.querySelector('[data-kind="activity_segment"] strong')).toHaveTextContent('Markdown');
    const order = () => Array.from(view.container.querySelectorAll('[data-kind="tool_call"]')).map((node) => node.textContent);
    expect(order()).toHaveLength(7); // six external tools and the failed internal tool
    for (const [index, number] of [1, 2, 3, 5, 6, 7].entries()) expect(order()[index]).toContain(`Command ${number}`);
    expect(order()[6]).toContain('read_tool_output');
    expect(view.container.querySelectorAll('[data-tool-status="failed"]')).toHaveLength(3);
    const button = view.container.querySelector('[data-kind="activity_segment"] > button')!;
    preferences.set(value({ auto_recap: false }));
    await waitFor(() => expect(button).toHaveAttribute('aria-expanded', 'true'));
    preferences.set(value({ keep_assistant_messages_separate: true }));
    await waitFor(() => expect(view.container.querySelector('[data-kind="activity_segment_assistant"]')).toBeNull());
    await expand(view.container);
    expect(view.container.querySelectorAll('strong')).toHaveLength(1);
    expect(order()).toHaveLength(7);
    preferences.set(value({ group_tool_calls: false }));
    await waitFor(() => expect(view.container.querySelector('[data-kind="activity_segment"], [data-kind="tool_group"]')).toBeNull());
    expect(order()).toHaveLength(7);
    expect(view.container.querySelectorAll('strong')).toHaveLength(1);
  });

  it('toggles thinking/internal visibility live and keeps historical recaps independent of auto generation', async () => {
    preferences.set(value({ group_tool_calls: false }));
    const view = mount(compact);
    await waitFor(() => expect(view.container.querySelectorAll('[data-kind="tool_call"]')).toHaveLength(7));
    expect(view.container.querySelector('[data-kind="thinking"]')).toBeNull();
    preferences.set(value({ group_tool_calls: false, show_thinking_blocks: true, show_internal_tool_calls: true, auto_recap: false }));
    await waitFor(() => expect(view.container.querySelectorAll('[data-kind="tool_call"]')).toHaveLength(8));
    expect(view.container.querySelector('[data-kind="thinking"]')).not.toBeNull();
    expect(view.container.textContent).toContain('Historical recap');
    const incoming = { ...items.at(-1)!, id: 'incoming-recap', sort_key: '0012', text: 'Incoming canonical recap' } as TimelineItem;
    view.emit({
      type: 'chat_v2_frame', schema_version: 2, projection_version: 'test', conversation_id: scope.conversation_id!,
      scope, cursor_before: 'settings-cursor', cursor_after: 'settings-next',
      ops: [{ op: 'upsert_item', item: incoming }], runtime: null, server_time: '',
    });
    await waitFor(() => expect(view.container.textContent).toContain('Incoming canonical recap'));
    expect(view.container.querySelectorAll('[aria-label="Conversation recap"]')).toHaveLength(2);
    preferences.set(value({ show_thinking_blocks: true, show_internal_tool_calls: true, keep_assistant_messages_separate: true }));
    await waitFor(() => expect(view.container.querySelector('[data-kind="thinking_group"]')).not.toBeNull());
    await expand(view.container);
    expect(view.container.querySelectorAll('[data-kind="tool_call"]')).toHaveLength(8);
    preferences.set(value({ show_thinking_blocks: false, keep_assistant_messages_separate: true }));
    await waitFor(() => expect(view.container.querySelector('[data-kind="thinking_group"]')).toBeNull());
    await expand(view.container);
    expect(view.container.querySelectorAll('[data-kind="tool_call"]')).toHaveLength(7);
  });

  it('honors an explicit Scoped override until removed', async () => {
    const override = value({ group_tool_calls: false, show_internal_tool_calls: true });
    const view = mount(compact, override);
    await waitFor(() => expect(view.container.querySelectorAll('[data-kind="tool_call"]')).toHaveLength(8));
    preferences.set(value({ group_tool_calls: true }));
    await waitFor(() => expect(view.container.querySelectorAll('[data-kind="tool_call"]')).toHaveLength(8));
    expect(view.container.querySelector('[data-kind="tool_group"]')).toBeNull();
    await view.rerender({ preferences: undefined });
    await waitFor(() => expect(view.container.querySelector('[data-kind="activity_segment"]')).not.toBeNull());
  });
});

it('changes Enter behavior on the mounted shared composer without remounting', async () => {
  preferences.set(value({ enter_to_send: false }));
  const onSend = vi.fn();
  const view = render(ChatV2Composer, { value: 'Draft', attachments: [], onSend, onStop: vi.fn(), onFiles: vi.fn() });
  const textarea = view.container.querySelector('textarea')!;
  await fireEvent.keyDown(textarea, { key: 'Enter' });
  expect(onSend).not.toHaveBeenCalled();
  preferences.set(value({ enter_to_send: true }));
  await waitFor(async () => {
    await fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
  });
  await fireEvent.keyDown(textarea, { key: 'Enter' });
  expect(onSend).toHaveBeenCalledTimes(1);
  await fireEvent.keyDown(textarea, { key: 'Enter', isComposing: true });
  expect(onSend).toHaveBeenCalledTimes(1);
});
