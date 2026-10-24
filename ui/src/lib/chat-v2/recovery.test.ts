import { describe, expect, it } from 'vitest';
import { selectFailedTurnRecovery } from './recovery';
import type { MessageTimelineItem, RuntimeOverlaySnapshot, TimelineItem } from './types';

function message(sort: string, overrides: Partial<MessageTimelineItem> = {}): MessageTimelineItem {
  return {
    id: sort, sort_key: sort, source_refs: [], stable: true,
    kind: 'message', role: 'system', message_id: sort, turn_id: 'turn-1',
    content: '', attachments: [], partial: false, ...overrides,
  };
}
const user = message('1', { role: 'user', content: 'Do the work' });
const commentary = message('2', { role: 'assistant', content: 'Checking the task.' });
const failure = message('3', {
  content: 'Provider message: Inference limit state unavailable',
  notice_kind: 'model_error', notice_scope: 'failed_turn', recoverable: true,
});
const items = [user, commentary, failure];
const runtime: RuntimeOverlaySnapshot = {
  runtime_epoch: 'epoch', runtime_revision: 1, generated_at: '2026-10-24T09:00:00Z',
  has_active_turn: false, volatile_items: [],
};

describe('unresolved failed-turn recovery', () => {
  it('preserves the real cause despite earlier completed assistant commentary', () => {
    expect(selectFailedTurnRecovery(items, runtime)).toEqual({
      turnId: 'turn-1', message: failure.content,
    });
  });

  it('uses structured error details when there is no model-error message', () => {
    const error: TimelineItem = {
      id: 'error', sort_key: '3', source_refs: [], stable: true, kind: 'error',
      turn_id: 'turn-1', level: 'error', title: 'Turn failed', recoverable: true,
      message: 'Model failed', error_detail: 'Connection reset by peer',
    };
    expect(selectFailedTurnRecovery([user, commentary, error], runtime)?.message)
      .toBe('Connection reset by peer');
  });

  it('uses current authority when a long turn has paged the user message out of the snapshot', () => {
    const current = {
      ...runtime, authority: {
        direct_request_id: 'request-1', turn_id: 'turn-1', fencing_token: 1,
        lifecycle: 'terminal' as const,
      },
    };
    expect(selectFailedTurnRecovery([commentary, failure], current)?.turnId).toBe('turn-1');
  });

  it.each(['starting', 'running', 'waiting', 'cancelling'] as const)(
    'hides controls while a turn is %s', (status) => {
      expect(selectFailedTurnRecovery(items, {
        ...runtime, has_active_turn: true,
        active_turn: { turn_id: 'turn-1', session_id: 'session-1', status },
      })).toBeNull();
    },
  );

  it('hides immediately during admission and after an accepted retry', () => {
    expect(selectFailedTurnRecovery(items, runtime, { pending: true })).toBeNull();
    expect(selectFailedTurnRecovery(items, runtime, { suppressedTurnId: 'turn-1' })).toBeNull();
  });

  it('hides during durable recovery even when the snapshot has no live overlay', () => {
    expect(selectFailedTurnRecovery(items, {
      ...runtime, authority: {
        direct_request_id: 'request-1', turn_id: 'turn-1', fencing_token: 1,
        lifecycle: 'recoverable',
      },
    })).toBeNull();
  });

  it('does not resurrect after a newer message, including a delayed old error', () => {
    for (const turn_id of [null, 'turn-2']) {
      const newer = message('4', { role: 'user', turn_id, stable: turn_id !== null });
      const delayed = { ...failure, sort_key: '5' };
      expect(selectFailedTurnRecovery([...items, newer, delayed], runtime)).toBeNull();
    }
  });

  it('does not resurrect after recovery or reload with a newer authority', () => {
    expect(selectFailedTurnRecovery([...items, message('4', { role: 'assistant' })], runtime))
      .toBeNull();
    const recovered = {
      ...runtime, authority: {
        direct_request_id: 'request-2', turn_id: 'turn-2', fencing_token: 1,
        lifecycle: 'terminal' as const,
      },
    };
    expect(selectFailedTurnRecovery(items, recovered)).toBeNull();
  });

  it('follows retry lineage and permits retrying a failed retry without duplicating the user', () => {
    const retry = message('4', {
      turn_id: 'turn-2', retry_source_turn_id: 'turn-1',
      notice_kind: 'model_recovery', notice_scope: 'turn',
    });
    expect(selectFailedTurnRecovery([...items, retry], runtime)).toBeNull();
    const failedRetry = { ...failure, id: 'failed-retry', sort_key: '5', turn_id: 'turn-2' };
    expect(selectFailedTurnRecovery([...items, retry, failedRetry], runtime)?.turnId).toBe('turn-2');
  });

  it('does not expose resolved or nonrecoverable errors as actionable failures', () => {
    expect(selectFailedTurnRecovery([user, { ...failure, recoverable: false }], runtime)).toBeNull();
    expect(selectFailedTurnRecovery([user, { ...failure, notice_resolved: true }], runtime)).toBeNull();
  });
});
