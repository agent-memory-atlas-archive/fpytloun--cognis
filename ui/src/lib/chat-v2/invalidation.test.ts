import { describe, expect, it } from 'vitest';
import { invalidatesTimeline } from './invalidation';
import type { TimelineScope } from './types';
import type { WebSocketScopeInvalidatedEvent } from '$lib/types/api';

describe('upstream canonical recovery policy parity', () => {
  const scope: TimelineScope = { kind: 'conversation', key: 'conversation:conv-1', conversation_id: 'conv-1' };
  it('recovers canonical state only for matching or global invalidations', () => {
    expect(invalidatesTimeline(scope, { conversation_id: 'conv-1' })).toBe(true);
    expect(invalidatesTimeline(scope, {})).toBe(true);
    expect(invalidatesTimeline(scope, { conversation_id: 'conv-2' })).toBe(false);
  });
  it.each(['executor_state_changed', 'schedule_action_changed'])(
    'does not rebuild canonical history for %s', reason => {
      expect(invalidatesTimeline(scope, { reason })).toBe(false);
      expect(invalidatesTimeline(scope, { reason, conversation_id: 'conv-1' })).toBe(false);
      expect(invalidatesTimeline(scope, { reason, scope_key: scope.key })).toBe(false);
    },
  );
  it.each(['chat_scope_changed', 'sidebar_changed', 'notification_state_changed', 'future_change'])(
    'retains canonical recovery for %s', reason => {
      expect(invalidatesTimeline(scope, { reason })).toBe(true);
      expect(invalidatesTimeline(scope, { reason, conversation_id: 'conv-2' })).toBe(false);
    },
  );
  it('requests canonical recovery after reconnect even without a sequence gap', () => {
    expect(invalidatesTimeline(scope, {})).toBe(true);
  });
  it.each([
    { scope_key: 'session:foreign' }, { session_id: 'foreign' },
    { task_id: 'foreign' }, { step_run_id: 'foreign' },
  ])('does not misclassify foreign routing as global: %j', routing => {
    expect(invalidatesTimeline(scope, { reason: 'future_change', ...routing })).toBe(false);
    expect(invalidatesTimeline(scope, { reason: 'event_store_session_invalidated', ...routing })).toBe(false);
    expect(invalidatesTimeline(scope, { scope_key: scope.key, ...routing })).toBe(false);
  });
  it('retains authorized opaque post-append hints only when routing does not conflict', () => {
    expect(invalidatesTimeline(scope, { reason: 'event_store_session_invalidated' })).toBe(true);
    expect(invalidatesTimeline(scope, {
      reason: 'event_store_session_invalidated', scope_key: scope.key, conversation_id: 'foreign',
    })).toBe(false);
  });
});

describe('canonical invalidation scope admission', () => {
  const scope: TimelineScope = {
    key: 'session:child', kind: 'session', session_id: 'child', conversation_id: 'conversation',
  };
  const event: WebSocketScopeInvalidatedEvent = {
    type: 'scope_invalidated', reason: 'chat_scope_changed',
    conversation_id: 'conversation', revision: 'admission',
  };
  it('does not admit conversation queue hints into a child scope', () => {
    expect(invalidatesTimeline(scope, event)).toBe(false);
  });
  it('matches explicit scope routing, not another session in the same conversation', () => {
    expect(invalidatesTimeline(scope, { ...event, scope_key: scope.key })).toBe(true);
    expect(invalidatesTimeline(scope, { ...event, scope_key: 'session:other' })).toBe(false);
    expect(invalidatesTimeline(scope, { ...event, session_id: 'other' })).toBe(false);
    expect(invalidatesTimeline(scope, { ...event, session_id: 'child' })).toBe(true);
  });
  it('rejects another conversation and missing streams', () => {
    expect(invalidatesTimeline(scope, { ...event, conversation_id: 'other', scope_key: scope.key })).toBe(false);
    expect(invalidatesTimeline({ ...scope, missing_stream: true }, { ...event, scope_key: scope.key })).toBe(false);
  });
});
