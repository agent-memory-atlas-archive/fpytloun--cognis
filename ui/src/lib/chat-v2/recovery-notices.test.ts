import { describe, expect, it } from 'vitest';
import { maybeApplyRuntime } from './sync-engine';
import { isRenderableTimelineItem, selectActivePinnedTransientNotice } from './selectors';
import type { MessageTimelineItem, RuntimeOverlaySnapshot } from './types';

function notice(id: string, resolved = false): MessageTimelineItem {
  return {
    id, message_id: id, notice_id: id, kind: 'message', role: 'system',
    content: 'Retrying', sort_key: id, source_refs: [], stable: false,
    attachments: [], partial: false, turn_id: 'turn-recovery',
    notice_kind: 'model_recovery', notice_scope: 'retry', notice_resolved: resolved,
  };
}

function runtime(revision: number, items: MessageTimelineItem[]): RuntimeOverlaySnapshot {
  return {
    runtime_epoch: 'recovery-test', runtime_revision: revision,
    generated_at: `2026-09-26T11:00:0${revision}Z`, has_active_turn: true,
    active_turn: { turn_id: 'turn-recovery', session_id: 'session-recovery', status: 'running' },
    volatile_items: items,
  };
}

describe('recovery notice lifecycle', () => {
  it('retires a retry in the same active turn and does not resurrect on partial replay', () => {
    const waiting = runtime(1, [notice('retry-first')]);
    expect(selectActivePinnedTransientNotice(waiting)?.id).toBe('retry-first');
    const resolved = maybeApplyRuntime(waiting, runtime(2, [notice('retry-first', true)]))!;
    expect(resolved.has_active_turn).toBe(true);
    expect(selectActivePinnedTransientNotice(resolved)).toBeNull();
    expect(resolved.volatile_items.filter(isRenderableTimelineItem)).toEqual([]);
    const replay = maybeApplyRuntime(resolved, runtime(3, [notice('retry-first')]))!;
    expect(selectActivePinnedTransientNotice(replay)).toBeNull();
    // A new retry has its own identity; resolving an earlier retry cannot hide it.
    const next = maybeApplyRuntime(replay, runtime(4, [notice('retry-second')]))!;
    expect(selectActivePinnedTransientNotice(next)?.id).toBe('retry-second');
    expect(selectActivePinnedTransientNotice(
      maybeApplyRuntime(next, runtime(5, [notice('retry-first', true)]))
    )?.id).toBe('retry-second');
  });

  it('hides hydrated resolved waits but preserves durable continuation history', () => {
    const resolved = runtime(1, [notice('retry-first', true)]);
    expect(selectActivePinnedTransientNotice(resolved)).toBeNull();
    expect(isRenderableTimelineItem({ ...notice('intaris', true), notice_scope: 'transient_retry' })).toBe(false);
    expect(isRenderableTimelineItem({
      ...notice('continuation'), stable: true, notice_scope: 'continuation'
    })).toBe(true);
  });
});
