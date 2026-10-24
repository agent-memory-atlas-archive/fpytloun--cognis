import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  clearSessionInfoCache,
  getSessionInfo,
  mergeRuntimeSelection,
  mergeSessionInfo,
  mergeSessionContextUsage,
  sessionInfoFromDetail,
  setSessionInfo,
  type SessionInfoData
} from './sessionInfoCache';
import type { ContextUsage, IntarisSessionDetail } from '$lib/types/api';

function detail(id: string): SessionInfoData {
  return {
    intaris_session_id: id, intention: null, summary: null, status: 'complete',
    total_calls: 0, approved_count: 0, denied_count: 0, escalated_count: 0,
  };
}

describe('sessionInfoCache', () => {
  beforeEach(() => clearSessionInfoCache());

  it('rejects an older runtime selection', () => {
    const current = {
      ...detail('session'),
      runtime_selection: {
        revision: 3,
        profile_id: 'developer',
        profile_source: 'session',
        model: 'new-model',
        provider_id: 'codex',
        model_source: 'session_override',
        reasoning_effort: 'high',
        reasoning_effort_source: 'session_override',
        fast_mode: null,
        fast_mode_source: 'agent_profile'
      }
    };
    const merged = mergeRuntimeSelection(current, {
      ...current.runtime_selection,
      revision: 2,
      model: 'old-model'
    });
    expect(merged).toBe(current);
  });

  it('retains details for two minutes and expires them by five minutes', () => {
    vi.useFakeTimers();
    setSessionInfo('conversation', 'session', detail('session'));
    vi.advanceTimersByTime(119_999);
    expect(getSessionInfo('conversation', 'session')?.intaris_session_id).toBe('session');
    vi.advanceTimersByTime(2);
    expect(getSessionInfo('conversation', 'session')).toBeNull();
    vi.useRealTimers();
  });

  it('preserves API serving provenance and newer diagnostics across stale responses', () => {
    const old = {
      ...detail('session'),
      context_usage: { model: 'gpt-6.1-sol', runtime_metadata_revision: 4 } as ContextUsage,
      inference_target: { provider_id: 'codex', model: 'gpt-6.1-sol', requested: 'cognis/chat', reason: 'bound' },
    };
    const next = sessionInfoFromDetail({
      ...detail('session'), session_id: 'session', title: null,
      context_usage: { model: 'claude-opus-5-5', runtime_metadata_revision: 5 } as ContextUsage,
      inference_target: { provider_id: 'anthropic', model: 'claude-opus-5-5', requested: 'cognis/chat', reason: 'fallback' },
    } as IntarisSessionDetail);
    expect(next.inference_target?.provider_id).toBe('anthropic');
    const merged = mergeSessionInfo(old, next);
    setSessionInfo('conversation', 'session', merged);
    expect(getSessionInfo('conversation', 'session')?.context_usage?.model).toBe('claude-opus-5-5');
    const stale = mergeSessionInfo(merged, old);
    expect(stale.context_usage?.model).toBe('claude-opus-5-5');
    expect(stale.inference_target?.provider_id).toBe('anthropic');
  });

  it('invalidates an old serving target when newer live context reports a model switch', () => {
    const initial = {
      ...detail('session'),
      context_usage: { model: 'gpt-6.1-sol', runtime_metadata_revision: 4 } as ContextUsage,
      inference_target: { provider_id: 'codex', model: 'gpt-6.1-sol', requested: 'cognis/chat', reason: 'bound' },
    };
    const live = { model: 'claude-opus-5-5', provider_id: 'anthropic', runtime_metadata_revision: 5 } as ContextUsage;
    const updated = mergeSessionContextUsage(initial, live);
    expect(updated.inference_target).toBeNull();
    expect(updated.context_usage?.provider_id).toBe('anthropic');
    const stale = mergeSessionInfo(updated, initial);
    expect(stale.inference_target).toBeNull();
    expect(stale.context_usage?.model).toBe('claude-opus-5-5');
    const absent = mergeSessionContextUsage(updated, null);
    expect(absent.context_usage?.model).toBe('claude-opus-5-5');
    expect(absent.inference_target).toBeNull();
  });

  it('keeps eight sessions per conversation and sixteen globally', () => {
    for (let index = 0; index < 10; index += 1) {
      setSessionInfo('conversation', `session-${index}`, detail(`session-${index}`));
    }
    expect(getSessionInfo('conversation', 'session-0')).toBeNull();
    expect(getSessionInfo('conversation', 'session-2')).not.toBeNull();
    for (let index = 0; index < 10; index += 1) {
      setSessionInfo(`other-${index}`, 'session', detail(`other-${index}`));
    }
    expect(getSessionInfo('conversation', 'session-3')).toBeNull();
  });
});
