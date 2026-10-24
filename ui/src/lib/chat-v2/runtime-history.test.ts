import { describe, expect, it } from 'vitest';
import { runtimeHistoryVisibility } from './runtime-history';
import type { MessageTimelineItem, TimelineItem } from './types';

function message(overrides: Partial<MessageTimelineItem> = {}): MessageTimelineItem {
  return {
    id: 'message:earlier', kind: 'message', role: 'assistant', message_id: 'earlier',
    content: 'Earlier progress', status: 'complete', partial: false, attachments: [],
    stable: false, source_refs: [], sort_key: '9998:999999999999999:000001:02:000000000',
    turn_id: 'turn-1', turn_cycle_index: 2, assistant_phase_index: 1,
    ...overrides
  };
}

const canonical = message({
  id: 'message:latest', message_id: 'latest', turn_cycle_index: 40, assistant_phase_index: 30,
  stable: true, sort_key: '0000:000000000001140:000030:02:000000000',
  source_refs: [{ store: 'intaris', session_id: 'sess-1', seq: 1140, event_type: 'assistant_message' }]
});

describe('completed runtime history visibility', () => {
  it.each(['complete', 'failed', 'cancelled', 'denied'] as const)(
    'defers older %s assistant history to canonical backfill', status => {
      expect(runtimeHistoryVisibility([canonical])(message({ status }))).toBe(false);
    }
  );

  it.each(['pending', 'waiting', 'running', undefined] as const)(
    'preserves %s work even when later canonical history exists', status => {
      expect(runtimeHistoryVisibility([canonical])(message({ status }))).toBe(true);
    }
  );

  it.each([
    { turn_id: null }, { turn_id: '' }, { turn_id: 'turn-2' },
    { turn_cycle_index: null }, { turn_cycle_index: undefined }, { turn_cycle_index: -1 },
    { turn_cycle_index: 40 }, { turn_cycle_index: 41 }, { turn_cycle_index: 2.5 },
    { assistant_phase_index: null }, { assistant_phase_index: undefined }, { assistant_phase_index: -1 },
    { assistant_phase_index: 30 }, { assistant_phase_index: 31 }, { assistant_phase_index: 1.5 }
  ])('preserves unknown, unrelated, equal or later coordinates: %j', overrides => {
    expect(runtimeHistoryVisibility([canonical])(message(overrides))).toBe(true);
  });

  it.each([
    { turn_id: null }, { turn_id: 'turn-2' },
    { turn_cycle_index: null }, { turn_cycle_index: undefined }, { turn_cycle_index: -1 },
    { assistant_phase_index: null }, { assistant_phase_index: undefined }, { assistant_phase_index: -1 }
  ])('does not use incomplete or unrelated canonical witnesses: %j', overrides => {
    expect(runtimeHistoryVisibility([message({ ...canonical, ...overrides })])(message())).toBe(true);
  });

  it('does not combine conflicting cycle and phase witnesses', () => {
    const keep = runtimeHistoryVisibility([
      message({ ...canonical, turn_cycle_index: 40, assistant_phase_index: 1 }),
      message({ ...canonical, id: 'message:other', turn_cycle_index: 2, assistant_phase_index: 30 })
    ]);
    expect(keep(message())).toBe(true);
  });

  it('preserves canonical identity matches for runtime metadata merging', () => {
    const earlier = message({ stable: true, sort_key: '0000:000000000000263:000001:02:000000000' });
    expect(runtimeHistoryVisibility([earlier, canonical])(message())).toBe(true);
  });

  it('never suppresses user or system messages', () => {
    const keep = runtimeHistoryVisibility([canonical]);
    expect(keep(message({ role: 'user' }))).toBe(true);
    expect(keep(message({ role: 'system' }))).toBe(true);
  });

  it('handles terminal thinking and tool history without affecting live siblings', () => {
    const thinking: TimelineItem = {
      id: 'thinking:earlier', kind: 'thinking', status: 'complete', stable: false, source_refs: [],
      sort_key: '9998:999999999999999:000001:01:000000000',
      turn_id: 'turn-1', turn_cycle_index: 2, assistant_phase_index: 1, blocks: []
    };
    const tool: TimelineItem = {
      id: 'tool:earlier', kind: 'tool_call', status: 'complete', stable: false, source_refs: [],
      sort_key: '9998:999999999999999:000001:03:000000000',
      turn_id: 'turn-1', turn_cycle_index: 2, assistant_phase_index: 1,
      call_id: 'earlier', tool_name: 'read', attachments: [], file_diffs: [],
      is_error: false, truncated: false, has_full_output: false
    };
    const keep = runtimeHistoryVisibility([canonical]);
    expect(keep(thinking)).toBe(false);
    expect(keep(tool)).toBe(false);
    expect(keep({ ...thinking, status: 'running' })).toBe(true);
    expect(keep({ ...tool, status: 'running' })).toBe(true);
    expect(runtimeHistoryVisibility([tool, canonical])(tool)).toBe(true);
  });
});
