import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import ProviderUsageBars from './ProviderUsageBars.svelte';
import type { ProviderUsage } from '$lib/types/api';

const usage = {
  ok: true, source: 'anthropic_subscription_usage', provider_id: 'claude',
  primary: { used_percent: 12, window_duration_mins: 300, resets_at: '2026-10-02T12:00:00Z' },
  secondary: { used_percent: 70, window_duration_mins: 10080, resets_at: '2026-10-08T12:00:00Z' },
  additional_rate_limits: [{ limit_name: 'Sonnet', primary: { used_percent: 69 } }]
} as ProviderUsage;

describe('shared provider usage bars', () => {
  it('labels each compact bar and consistently displays used percentages', () => {
    render(ProviderUsageBars, { usage, compact: true });
    expect(screen.getAllByRole('progressbar')).toHaveLength(3);
    expect(screen.getByRole('progressbar', { name: '5-hour usage' })).toHaveAttribute('aria-valuenow', '12');
    expect(screen.getByRole('progressbar', { name: 'Weekly usage' })).toHaveAttribute('aria-valuenow', '70');
    expect(screen.getByRole('progressbar', { name: 'Sonnet usage' })).toHaveAttribute('aria-valuenow', '69');
    expect(screen.getByText('12% used')).toBeInTheDocument();
    expect(screen.queryByText(/% left/)).not.toBeInTheDocument();
  });
  it('retains detailed sidebar rolling labels and individual reset times', () => {
    render(ProviderUsageBars, { usage });
    expect(screen.getByText('5-hour rolling limit')).toBeInTheDocument();
    expect(screen.getByText('Weekly rolling limit')).toBeInTheDocument();
    expect(screen.getAllByText(/^Resets /)).toHaveLength(2);
  });
  it('uses the spare compact grid cell for labelled visible reset dates', () => {
    render(ProviderUsageBars, { usage, compact: true });
    const summary = screen.getByTestId('compact-limit-resets');
    expect(summary).not.toHaveClass('col-span-2');
    expect(screen.getByText('5-hour reset')).toBeInTheDocument();
    expect(screen.getByText('Weekly reset')).toBeInTheDocument();
    expect(summary.querySelectorAll('time')).toHaveLength(2);
    expect(summary.querySelector('time')).toHaveAttribute('datetime', '2026-10-02T12:00:00Z');
  });
  it('omits unavailable or invalid reset times', () => {
    render(ProviderUsageBars, { compact: true, usage: {
      ...usage, primary: { ...usage.primary!, resets_at: null },
      secondary: { ...usage.secondary!, resets_at: 'not a timestamp' }
    } });
    expect(screen.queryByTestId('compact-limit-resets')).not.toBeInTheDocument();
    expect(screen.queryByText('Reset time unavailable')).not.toBeInTheDocument();
  });
});
