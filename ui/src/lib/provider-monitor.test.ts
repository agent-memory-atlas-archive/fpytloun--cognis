import { get, writable } from 'svelte/store';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProviderMonitor } from '$lib/types/api';

const { monitor, refreshMonitor } = vi.hoisted(() => ({ monitor: vi.fn(), refreshMonitor: vi.fn() }));
vi.mock('$lib/api/client', () => ({ api: { llmProviders: { monitor, refreshMonitor } } }));
vi.mock('$lib/stores/auth', () => {
  const store = writable({ user: { email: 'owner@cognis.test', role: 'user' } });
  return { auth: { subscribe: store.subscribe, getSnapshot: () => get(store), setTestUser: (email: string) => store.set({ user: { email, role: 'user' } }) } };
});
import { auth } from '$lib/stores/auth';
import { freshnessTone, invalidateProviderMonitor, loadProviderMonitor, providerMonitoring, publishProviderMonitors, quotaSummary } from './provider-monitor';

export function snapshot(overrides: Partial<ProviderMonitor> = {}): ProviderMonitor {
  return {
    provider_id: 'claude', display_name: 'Claude', monitoring: { enabled: true, interval_minutes: 15, warning_percent: 20, critical_percent: 0 },
    health_status: 'healthy', health_detail: 'Reachable', health_checked_at: new Date().toISOString(), checked_at: new Date().toISOString(),
    next_refresh_at: new Date(Date.now() + 900_000).toISOString(), usage: null, error: null, alert_severity: null, stale: false,
    ...overrides
  };
}

describe('provider monitor cache', () => {
  beforeEach(() => { (auth as typeof auth & { setTestUser: (email: string) => void }).setTestUser('owner@cognis.test'); providerMonitoring.set({}); monitor.mockReset(); refreshMonitor.mockReset(); });
  it('reuses fresh values across consumers and forces only explicit refresh', async () => {
    const value = snapshot();
    publishProviderMonitors([value]);
    expect(await loadProviderMonitor('claude')).toEqual(value);
    expect(monitor).not.toHaveBeenCalled();
    refreshMonitor.mockResolvedValue(value);
    await loadProviderMonitor('claude', true);
    expect(refreshMonitor).toHaveBeenCalledOnce();
  });
  it('does not automatically refresh expired manual-only usage', async () => {
    publishProviderMonitors([snapshot({ next_refresh_at: '2020-01-01T00:00:00Z', monitoring: { enabled: false, interval_minutes: 15, warning_percent: 20, critical_percent: 0 } })]);
    await loadProviderMonitor('claude');
    expect(monitor).not.toHaveBeenCalled();
  });
  it('coalesces concurrent refreshes', async () => {
    const value = snapshot();
    refreshMonitor.mockResolvedValue(value);
    await Promise.all([loadProviderMonitor('claude', true), loadProviderMonitor('claude', true)]);
    expect(refreshMonitor).toHaveBeenCalledOnce();
  });
  it('drops manual-only observations after credential invalidation for every consumer', async () => {
    const old = snapshot({ monitoring: { enabled: false, interval_minutes: 15, warning_percent: 20, critical_percent: 0 } });
    publishProviderMonitors([old]);
    const consumers: (ProviderMonitor | undefined)[] = [];
    const unsubscribe = providerMonitoring.subscribe((values) => consumers.push(values.claude));
    invalidateProviderMonitor('claude');
    expect(get(providerMonitoring).claude).toBeUndefined();
    expect(consumers.at(-1)).toBeUndefined();
    const cleared = snapshot({ monitoring: old.monitoring, health_status: 'unknown', health_checked_at: null, checked_at: null });
    monitor.mockResolvedValue(cleared);
    await loadProviderMonitor('claude');
    expect(get(providerMonitoring).claude).toEqual(cleared);
    expect(refreshMonitor).not.toHaveBeenCalled();
    unsubscribe();
  });
  it('does not restore obsolete in-flight values after credential invalidation', async () => {
    let resolve!: (value: ProviderMonitor) => void;
    refreshMonitor.mockReturnValue(new Promise<ProviderMonitor>((done) => { resolve = done; }));
    const request = loadProviderMonitor('claude', true);
    invalidateProviderMonitor('claude');
    resolve(snapshot());
    await request;
    expect(get(providerMonitoring).claude).toBeUndefined();
  });
  it('never publishes a previous owner refresh into the next owner cache', async () => {
    let resolve!: (value: ProviderMonitor) => void;
    refreshMonitor.mockReturnValue(new Promise<ProviderMonitor>((done) => { resolve = done; }));
    const request = loadProviderMonitor('claude', true);
    (auth as typeof auth & { setTestUser: (email: string) => void }).setTestUser('other@cognis.test');
    resolve(snapshot());
    await request;
    expect(get(providerMonitoring)).toEqual({});
  });
  it('marks timestamps older than one hour with warning color', () => {
    expect(freshnessTone('2026-10-01T06:00:00Z', Date.parse('2026-10-01T08:00:00Z'))).toBe('text-warning');
    expect(freshnessTone('2026-10-01T07:45:00Z', Date.parse('2026-10-01T08:00:00Z'))).toBe('text-muted');
    expect(quotaSummary(snapshot())).toBe('Usage unknown');
  });
});
