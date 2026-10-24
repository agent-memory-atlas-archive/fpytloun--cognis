import { describe, expect, it } from 'vitest';
import {
  QUICK_PROFILE_RUNTIME_MAX_FAILURES,
  quickProfileOverrides,
  recordRuntimeForSession,
  shouldLoadRuntimeForSession,
  type RuntimeBySession
} from './agent-quick-switch';
import type { RuntimeSelection } from '$lib/types/api';

const cleanSelection: RuntimeSelection = {
  revision: 1, profile_id: 'developer', profile_source: 'conversation',
  model: 'gpt-5', provider_id: 'openai', model_source: 'agent_profile',
  reasoning_effort: 'medium', reasoning_effort_source: 'agent_profile',
  fast_mode: false, fast_mode_source: 'agent_profile'
};
const overridden: RuntimeSelection = { ...cleanSelection, revision: 2, fast_mode_source: 'session_override' };

describe('quickProfileOverrides', () => {
  it('does not mistake profile or inherited settings for overrides', () => {
    expect(quickProfileOverrides(cleanSelection)).toEqual([]);
    expect(quickProfileOverrides(null)).toEqual([]);
  });
  it.each(['model_source', 'reasoning_effort_source', 'fast_mode_source'] as const)(
    'identifies explicit %s override even when its value matches the profile', source => {
      expect(quickProfileOverrides({ ...cleanSelection, [source]: 'session_override' })).toHaveLength(1);
    });
  it('reports all overridden values including disabled fast mode', () => {
    expect(quickProfileOverrides({ ...cleanSelection, model_source: 'session_override',
      reasoning_effort_source: 'session_override', fast_mode_source: 'session_override' }))
      .toEqual(['Model: gpt-5', 'Thinking: medium', 'Fast mode: off']);
  });
});

describe('per-session runtime selection', () => {
  const none = new Set<string>();
  const noFailures = new Map<string, number>();

  it('keeps an overridden session intact across A -> B -> A navigation without reloading', () => {
    let map: RuntimeBySession = {};
    map = recordRuntimeForSession(map, 'A', overridden);
    map = recordRuntimeForSession(map, 'B', cleanSelection);
    expect(quickProfileOverrides(map.A)).toEqual(['Fast mode: off']);
    expect(quickProfileOverrides(map.B)).toEqual([]);
    expect(shouldLoadRuntimeForSession(map, 'A', none, noFailures)).toBe(false);
  });

  it('stores a result that arrives after navigating away for later return', () => {
    // The loader records by session id regardless of the currently open route.
    const map = recordRuntimeForSession({ B: cleanSelection }, 'A', overridden);
    expect(map.A).toBe(overridden);
    expect(shouldLoadRuntimeForSession(map, 'A', none, noFailures)).toBe(false);
  });

  it('never replaces a newer revision with an older one and avoids no-op copies', () => {
    const map = recordRuntimeForSession({}, 'A', overridden);
    expect(recordRuntimeForSession(map, 'A', cleanSelection)).toBe(map);
    expect(recordRuntimeForSession(map, 'A', overridden)).toBe(map);
    const cleared = { ...cleanSelection, revision: 3 };
    expect(recordRuntimeForSession(map, 'A', cleared).A).toBe(cleared);
  });

  it('deduplicates in-flight loads and bounds failures', () => {
    expect(shouldLoadRuntimeForSession({}, 'A', new Set(['A']), noFailures)).toBe(false);
    expect(shouldLoadRuntimeForSession({}, 'A', none, new Map([['A', 1]]))).toBe(true);
    expect(shouldLoadRuntimeForSession({}, 'A', none,
      new Map([['A', QUICK_PROFILE_RUNTIME_MAX_FAILURES]]))).toBe(false);
  });
});
