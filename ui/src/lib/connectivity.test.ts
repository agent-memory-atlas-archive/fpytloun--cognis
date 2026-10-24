import { describe, expect, it } from 'vitest';

import { combineConnectivity } from './connectivity';

const ws = (status: 'connected' | 'reconnecting' | 'stalled' | 'idle', extra: { offline?: boolean; lastError?: string | null; attempts?: number } = {}) => ({
  status,
  attempts: extra.attempts ?? 0,
  lastError: extra.lastError ?? null,
  offline: extra.offline,
});
const server = (state: 'ok' | 'unreachable' | 'restarting', lastFailure: string | null = null) => ({ state, lastFailure });

describe('combineConnectivity', () => {
  it('is healthy only when every source is', () => {
    expect(combineConnectivity(true, ws('connected'), server('ok'))).toMatchObject({ level: 'ok', degraded: false });
  });

  it('orders problems: offline > restarting > stalled > unreachable > reconnecting', () => {
    expect(combineConnectivity(false, ws('reconnecting'), server('restarting')).level).toBe('offline');
    expect(combineConnectivity(true, ws('connected', { offline: true }), server('ok')).level).toBe('offline');
    expect(combineConnectivity(true, ws('stalled'), server('restarting')).level).toBe('restarting');
    expect(combineConnectivity(true, ws('stalled'), server('unreachable')).level).toBe('stalled');
    expect(combineConnectivity(true, ws('reconnecting'), server('unreachable')).level).toBe('unreachable');
    expect(combineConnectivity(true, ws('reconnecting'), server('ok')).level).toBe('reconnecting');
  });

  it('detects an unresponsive server while the realtime socket still looks connected', () => {
    const state = combineConnectivity(true, ws('connected'), server('unreachable', 'Request timed out after 30 seconds.'));
    expect(state).toMatchObject({ level: 'unreachable', degraded: true, lastFailure: 'Request timed out after 30 seconds.' });
  });

  it('leaves a signed-out realtime stall to the login flow', () => {
    expect(combineConnectivity(true, ws('stalled', { lastError: 'Session expired. Please log in again.' }), server('ok')).degraded).toBe(false);
    expect(combineConnectivity(true, ws('stalled', { lastError: 'Authentication required' }), server('ok')).degraded).toBe(false);
  });
});
