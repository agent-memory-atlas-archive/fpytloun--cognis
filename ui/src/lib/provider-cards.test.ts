import { describe, expect, it } from 'vitest';
import { providerCards } from './provider-cards';
import type { ProviderMonitor } from '$lib/types/api';

function provider(id: string, bars = false): ProviderMonitor {
  return {
    provider_id: id, display_name: id,
    monitoring: { enabled: false, interval_minutes: 15, warning_percent: 20, critical_percent: 0 },
    health_status: 'unknown', health_detail: '', health_checked_at: null, checked_at: null,
    next_refresh_at: null, error: null, alert_severity: null, stale: true,
    usage: bars ? {
      provider_id: id, ok: true, source: 'chatgpt_codex_usage', usage_url: null, fetched_at: null,
      plan_type: null, secondary: null, credits: null, rate_limit_reached_type: null, allowed: true,
      limit_reached: false, additional_rate_limits: [],
      primary: { used_percent: 25, window_duration_mins: 10080, resets_at: null, reset_after_seconds: null }
    } : null
  };
}

describe('provider cards', () => {
  it('fills short usage cards before stacking remaining health providers', () => {
    const items = [provider('claude', true), provider('local'), provider('codex', true), provider('proxy'), provider('extra')];
    expect(providerCards(items).map((card) => card.map((item) => item.provider_id)))
      .toEqual([['claude', 'local'], ['codex', 'proxy'], ['extra']]);
  });
  it('stacks up to four health-only providers in each card in source order', () => {
    const items = ['local', 'proxy', 'gemini', 'groq', 'openai'].map((id) => provider(id));
    expect(providerCards(items).map((card) => card.map((item) => item.provider_id)))
      .toEqual([['local', 'proxy', 'gemini', 'groq'], ['openai']]);
  });
  it('keeps multi-row usage reports separate, including additional limits', () => {
    const full = provider('claude', true);
    full.usage!.secondary = full.usage!.primary;
    full.usage!.additional_rate_limits = [{
      limit_name: 'Sonnet', limit_id: null, allowed: true, limit_reached: false,
      primary: full.usage!.primary, secondary: null
    }];
    const pair = provider('subscription', true);
    pair.usage!.secondary = pair.usage!.primary;
    expect(providerCards([full, pair, provider('codex', true), provider('local'), provider('proxy')])
      .map((card) => card.map((item) => item.provider_id)))
      .toEqual([['claude'], ['subscription', 'local'], ['codex', 'proxy']]);
  });
  it('treats unsupported and empty usage reports as health-only', () => {
    const empty = provider('empty', true);
    empty.usage!.primary = null;
    const failed = provider('failed', true);
    failed.usage!.ok = false;
    expect(providerCards([empty, failed, provider('local')])).toHaveLength(1);
    expect(providerCards([])).toEqual([]);
  });
  it('preserves every provider exactly once without mutating the input', () => {
    const items = [provider('local'), provider('codex', true), provider('proxy')];
    const before = structuredClone(items);
    const packed = providerCards(items).flat();
    expect(packed).toHaveLength(items.length);
    expect(new Set(packed)).toEqual(new Set(items));
    expect(items).toEqual(before);
  });
});
