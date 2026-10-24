import { cleanup, fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import SessionDetailsContent from './SessionDetailsContent.svelte';
import { providerMonitoring, publishProviderMonitors } from '$lib/provider-monitor';
import type { ProviderMonitor, ContextUsage, RuntimeSelection } from '$lib/types/api';

vi.mock('$lib/api/client', () => ({
  api: { llmProviders: { providerUsage: vi.fn() } },
}));

const detail = {
  session_id: 'session-a',
  intaris_session_id: 'intaris-a',
  intention: null,
  summary: 'A long session summary that must stay on one compact line until requested.',
  status: 'active',
  total_calls: 4,
  approved_count: 3,
  denied_count: 0,
  escalated_count: 1,
};

afterEach(() => { cleanup(); providerMonitoring.set({}); });

describe('SessionDetailsContent', () => {
  it('updates serving model and provider limits after a routed model switch', async () => {
    publishProviderMonitors([anthropicMonitor('anthropic', true)]);
    const contextUsage = { prompt_tokens: 100, max_context_tokens: 1000 } as ContextUsage;
    const { rerender } = render(SessionDetailsContent, {
      detail: { ...detail, inference_target: { provider_id: 'codex', model: 'gpt-6.1-sol',
        requested: 'cognis/chat', reason: 'bound' } }, sessionId: 'sess-test',
      contextUsage: { ...contextUsage, provider_id: 'codex', model: 'gpt-6.1-sol' },
    });
    expect(await screen.findByText('codex/gpt-6.1-sol')).toBeInTheDocument();
    await rerender({
      detail: { ...detail, inference_target: { provider_id: 'anthropic', model: 'claude-opus-5-5',
        requested: 'cognis/claude-opus', reason: 'fallback' } }, sessionId: 'sess-test',
      contextUsage: { ...contextUsage, provider_id: 'anthropic', model: 'claude-opus-5-5' },
    });
    expect(screen.getByText('anthropic/claude-opus-5-5')).toBeInTheDocument();
    expect(screen.getByText(/Last context: claude-opus-5-5/)).toBeInTheDocument();
    expect(screen.getByTestId('session-provider-usage-limits')).toHaveTextContent('Claude subscription limits');
    expect(screen.queryByText('codex/gpt-6.1-sol')).not.toBeInTheDocument();
  });
  const selection = (providerId: string): RuntimeSelection => ({
    revision: 1,
    profile_id: 'developer',
    profile_source: 'agent_default',
    model: 'claude-sonnet-4-6',
    provider_id: providerId,
    model_source: 'session_override',
    reasoning_effort: null,
    reasoning_effort_source: 'provider_default',
    fast_mode: null,
    fast_mode_source: 'provider_default',
  });

  it('uses live fallback provider limits without waiting for a detail response', async () => {
    publishProviderMonitors([
      anthropicMonitor('selected', false), anthropicMonitor('serving', true),
    ]);
    render(SessionDetailsContent, {
      detail: { ...detail, runtime_selection: selection('selected'), inference_target: null },
      contextUsage: { model: 'claude-opus-5-5', provider_id: 'serving',
        runtime_selection_revision: 1, prompt_tokens: 100, max_context_tokens: 1000 } as ContextUsage,
    });
    await screen.findByTestId('session-details-content');
    expect(screen.getByText('serving/claude-opus-5-5')).toBeInTheDocument();
    expect(screen.getByTestId('session-provider-usage-limits')).toHaveTextContent('Claude subscription limits');
    expect(screen.getByTestId('session-provider-usage-limits')).toHaveTextContent('58% used');
  });

  function anthropicMonitor(providerId: string, subscription: boolean): ProviderMonitor {
    return {
      provider_id: providerId, display_name: providerId,
      monitoring: { enabled: false, interval_minutes: 15, warning_percent: 20, critical_percent: 0 },
      health_status: 'healthy', health_detail: 'Reachable', checked_at: new Date().toISOString(),
      health_checked_at: new Date().toISOString(), next_refresh_at: null, error: null, stale: false, alert_severity: null,
      usage: {
        ok: true, source: subscription ? 'anthropic_subscription_usage' : 'anthropic_rate_limit_headers',
        provider_id: providerId, fetched_at: new Date().toISOString(),
        usage_url: null, plan_type: null, secondary: null, credits: null,
        rate_limit_reached_type: null, allowed: true, limit_reached: false,
        primary: { used_percent: subscription ? 58 : 12, window_duration_mins: 300, resets_at: null, reset_after_seconds: null },
        additional_rate_limits: [],
      },
    };
  }

  it('switches limits by selected provider ID while preserving the last context', async () => {
    publishProviderMonitors([
      anthropicMonitor('claude-subscription', true),
      anthropicMonitor('anthropic-api', false),
    ]);
    const contextUsage = {
      provider_id: 'claude-subscription', model: 'claude-sonnet-4-6',
      prompt_tokens: 100, max_context_tokens: 1000,
    } as ContextUsage;
    const view = render(SessionDetailsContent, {
      detail: { ...detail, runtime_selection: selection('claude-subscription') },
      contextUsage,
    });
    await screen.findByTestId('session-details-content');
    expect(screen.getByTestId('session-provider-usage-limits')).toHaveTextContent('58% used');

    await view.rerender({
      detail: { ...detail, runtime_selection: { ...selection('anthropic-api'), revision: 2 } },
      contextUsage,
    });
    const limits = screen.getByTestId('session-provider-usage-limits');
    expect(within(limits).getByTestId('provider-health-anthropic-api')).toBeInTheDocument();
    expect(limits).toHaveTextContent('Anthropic API rate limits');
    expect(limits).toHaveTextContent('12% used');
    expect(limits).not.toHaveTextContent('Claude subscription limits');
    expect(limits).not.toHaveTextContent('58% used');
    expect(screen.getByTestId('session-details-diagnostics')).toHaveTextContent('claude-subscription');
  });

  it('never shows old subscription limits when the selected provider has no monitor', async () => {
    publishProviderMonitors([anthropicMonitor('claude-subscription', true)]);
    render(SessionDetailsContent, {
      detail: { ...detail, runtime_selection: selection('anthropic-api') },
      contextUsage: {
        provider_id: 'claude-subscription', model: 'claude-sonnet-4-6',
        prompt_tokens: 100, max_context_tokens: 1000,
      } as ContextUsage,
    });
    await screen.findByTestId('session-details-content');
    const limits = screen.getByTestId('session-provider-usage-limits');
    expect(within(limits).getByTestId('provider-health-anthropic-api')).toBeInTheDocument();
    expect(limits).not.toHaveTextContent('Claude subscription limits');
    expect(limits).not.toHaveTextContent('58% used');
  });

  it('shows selected provider limits before any context usage exists', async () => {
    publishProviderMonitors([anthropicMonitor('anthropic-api', false)]);
    render(SessionDetailsContent, {
      detail: { ...detail, runtime_selection: selection('anthropic-api') },
    });
    await screen.findByTestId('session-details-content');
    expect(screen.getByTestId('session-provider-usage-limits')).toHaveTextContent('Anthropic API rate limits');
  });

  it('keeps subscription bars exclusively in their original limits column', async () => {
    publishProviderMonitors([{
      provider_id: 'codex', display_name: 'Codex',
      monitoring: { enabled: false, interval_minutes: 15, warning_percent: 20, critical_percent: 0 },
      health_status: 'healthy', health_detail: 'Reachable', checked_at: new Date().toISOString(),
      health_checked_at: new Date().toISOString(), next_refresh_at: null, error: null, stale: false, alert_severity: null,
      usage: { ok: true, source: 'chatgpt_codex_usage', provider_id: 'codex', fetched_at: new Date().toISOString(),
        usage_url: null, plan_type: null, secondary: null, credits: null, rate_limit_reached_type: null, allowed: true, limit_reached: false,
        primary: { used_percent: 58, window_duration_mins: 10080, resets_at: null, reset_after_seconds: null }, additional_rate_limits: [] }
    } satisfies ProviderMonitor]);
    render(SessionDetailsContent, { detail, contextUsage: {
      provider_id: 'codex', model: 'gpt-6.1-sol', prompt_tokens: 131564, max_context_tokens: 400000
    } as ContextUsage });
    await screen.findByTestId('session-details-content');
    const context = screen.getByText('Context window').closest('section')!;
    expect(within(context).queryByTestId('provider-health-codex')).not.toBeInTheDocument();
    const limits = screen.getByTestId('session-provider-usage-limits');
    expect(within(limits).getByText('Codex subscription limits')).toBeInTheDocument();
    expect(within(limits).getByRole('progressbar', { name: 'Weekly rolling limit usage' })).toHaveAttribute('aria-valuenow', '58');
    expect(screen.getAllByText('58% used')).toHaveLength(1);
    expect(screen.queryByText('58% left')).not.toBeInTheDocument();
  });
  it('shows an amber warning only when yolo is active', async () => {
    const view = render(SessionDetailsContent, { detail, yoloMode: true });
    await screen.findByTestId('session-details-content');
    const warning = screen.getByTestId('session-details-yolo-warning');
    expect(warning).toHaveAttribute('role', 'alert');
    expect(warning).toHaveClass('border-warning-border');
    expect(warning).toHaveTextContent('Yolo mode active');
    await view.rerender({ detail, yoloMode: false });
    expect(screen.queryByTestId('session-details-yolo-warning')).not.toBeInTheDocument();
  });

  it('keeps the narrative collapsed until the user expands it', async () => {
    render(SessionDetailsContent, { detail });
    await screen.findByTestId('session-details-content');

    const narrative = screen.getByTestId('session-narrative');
    expect(narrative).not.toHaveAttribute('open');
    expect(narrative.querySelector('.truncate')).toHaveTextContent(detail.summary);

    await fireEvent.click(screen.getByText('Summary'));
    expect(narrative).toHaveAttribute('open');
    expect(narrative).toHaveTextContent(detail.summary);
  });

  it('wraps cached-token statistics within the context card', async () => {
    render(SessionDetailsContent, {
      detail: {
        ...detail,
        token_usage: {
          prompt_tokens: 114303,
          completion_tokens: 2357,
          total_tokens: 116660,
          cache_read_input_tokens: 111835,
          cache_write_tokens: 2466,
        },
      },
    });

    await screen.findByTestId('session-details-content');
    const stats = screen.getByTestId('session-token-usage-stats');
    expect(stats).toHaveClass('flex-wrap');
    expect(stats).toHaveTextContent('Input 114,303');
    expect(stats).toHaveTextContent('Output 2,357');
    expect(stats).toHaveTextContent('Cache read 111,835');
    expect(stats).toHaveTextContent('Cache write 2,466');
    for (const stat of stats.querySelectorAll('span')) {
      expect(stat).toHaveClass('whitespace-nowrap');
    }
  });

  it.each([
    ['default', 'Provider default'],
    ['none', 'Disabled'],
    ['high', 'High'],
    [null, 'Inherit routing/provider configuration'],
  ])('separates selected thinking %s from the last context runtime', async (effort, label) => {
    render(SessionDetailsContent, {
      detail: {
        ...detail,
        runtime_selection: {
          revision: 2,
          profile_id: 'developer-deep',
          profile_source: 'session',
          model: 'gpt-6-astra',
          provider_id: 'codex',
          model_source: 'session_override',
          reasoning_effort: effort,
          reasoning_effort_source: effort === null ? 'provider_default' : 'session_override',
          fast_mode: false,
          fast_mode_source: 'session_override',
        },
        context_usage: {
          model: 'gpt-5.4',
          provider_id: 'openai',
          prompt_tokens: 100,
          max_context_tokens: 1000,
          percentage: 10,
          reasoning_effort: null,
        },
      },
    });

    await screen.findByTestId('session-details-content');
    expect(screen.getByTestId('session-selected-runtime')).toHaveTextContent('developer-deep');
    expect(screen.getByTestId('session-selected-runtime')).toHaveTextContent(
      'codex/gpt-6-astra'
    );
    expect(screen.getByText(/Last context:/)).toHaveTextContent('gpt-5.4');
    expect(screen.getByTestId('session-selected-runtime')).toHaveTextContent(label!);
    expect(screen.getByTestId('session-selected-runtime')).toHaveTextContent(
      effort === null ? 'Source: provider default' : 'Source: session override'
    );
  });

  it('renders Star as an icon-only action next to Open in Intaris', async () => {
    const onToggleStar = vi.fn();
    const onOpenIntaris = vi.fn();
    render(SessionDetailsContent, {
      detail,
      canStar: true,
      starred: false,
      onToggleStar,
      onOpenIntaris,
    });

    await screen.findByTestId('session-details-content');
    const star = screen.getByRole('button', { name: 'Star conversation' });
    expect(star).toHaveTextContent('');
    expect(screen.getByRole('button', { name: 'Open in Intaris' })).toBeTruthy();
    await fireEvent.click(star);
    expect(onToggleStar).toHaveBeenCalledOnce();
    await fireEvent.click(screen.getByRole('button', { name: 'Open in Intaris' }));
    expect(onOpenIntaris).toHaveBeenCalledExactlyOnceWith(detail.intaris_session_id);
  });

  it('hides lifecycle actions without eligible callbacks', async () => {
    const onArchive = vi.fn();
    const onDelete = vi.fn();
    render(SessionDetailsContent, { detail, onArchive, onDelete });
    await screen.findByTestId('session-details-content');
    expect(screen.queryByRole('button', { name: 'Archive' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
    expect(onArchive).not.toHaveBeenCalled();
    expect(onDelete).not.toHaveBeenCalled();
  });

  it('shows archive and delete and invokes their callbacks', async () => {
    const onArchive = vi.fn();
    const onDelete = vi.fn();
    render(SessionDetailsContent, {
      detail,
      canArchive: true,
      canDelete: true,
      onArchive,
      onDelete,
    });

    await screen.findByTestId('session-details-content');
    await fireEvent.click(screen.getByRole('button', { name: 'Archive' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(onArchive).toHaveBeenCalledOnce();
    expect(onDelete).toHaveBeenCalledOnce();
  });

  it('shows restore for archived conversations', async () => {
    const onRestore = vi.fn();
    render(SessionDetailsContent, {
      detail,
      canArchive: true,
      archived: true,
      onRestore,
    });

    await screen.findByTestId('session-details-content');
    await fireEvent.click(screen.getByRole('button', { name: 'Restore' }));
    expect(onRestore).toHaveBeenCalledOnce();
    expect(screen.queryByRole('button', { name: 'Archive' })).not.toBeInTheDocument();
  });

  it('shows busy labels and disables both lifecycle actions', async () => {
    render(SessionDetailsContent, {
      detail,
      canArchive: true,
      canDelete: true,
      archiveBusy: true,
      onArchive: vi.fn(),
      onDelete: vi.fn(),
    });

    await screen.findByTestId('session-details-content');
    expect(screen.getByRole('button', { name: 'Archiving…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled();
  });
});
