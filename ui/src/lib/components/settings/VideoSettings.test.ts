import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import VideoSettings from './VideoSettings.svelte';

const calls = vi.hoisted(() => ({ policy: vi.fn(), savePolicy: vi.fn(), list: vi.fn() }));
vi.mock('$lib/api/client', () => ({ api: { videos: calls, llmProviders: { list: calls.list } } }));
const policy = {
  enabled: false, per_job_usd: 5, daily_usd: 20, max_active_jobs: 2,
  max_output_bytes: 1000000, model_max_cost_usd: {}
};
beforeEach(() => {
  vi.clearAllMocks();
  calls.policy.mockResolvedValue({ ...policy });
  calls.savePolicy.mockImplementation(async (value) => value);
  calls.list.mockResolvedValue({ items: [{
    provider_id: 'gemini', display_name: 'Google', models: [
      { model_id: 'veo-3.1-generate-preview', model_mode: 'video', display_name: 'Veo 3.1' },
      { model_id: 'chat', model_mode: 'chat' },
    ]
  }] });
});

async function openPanel(container: HTMLElement) {
  const details = container.querySelector('details')!;
  details.open = true;
  await fireEvent(details, new Event('toggle'));
  await screen.findByLabelText('Apply video spending limits');
}

describe('optional account video limits', () => {
  it('retries model loading without resetting loaded policy', async () => {
    calls.list.mockRejectedValueOnce(new Error('Provider lookup unavailable'));
    const { container } = render(VideoSettings);
    await openPanel(container);
    await screen.findByRole('alert');
    await fireEvent.click(screen.getByRole('button', { name: 'Retry loading models' }));
    await waitFor(() => expect(calls.list).toHaveBeenCalledTimes(2));
    expect(calls.policy).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });
  it('stays collapsed and does not load until opened; excludes internal job/JSON controls', async () => {
    const { container } = render(VideoSettings);
    expect(container.querySelector('details')?.open).toBe(false);
    expect(calls.policy).not.toHaveBeenCalled();
    await openPanel(container);
    expect(screen.getByLabelText('Apply video spending limits')).not.toBeChecked();
    expect(screen.queryByLabelText('Per video (USD)')).not.toBeInTheDocument();
    expect(container.querySelector('textarea')).toBeNull();
    expect(screen.queryByText('Conversation ID')).not.toBeInTheDocument();
  });

  it('opts into limits with structured model rows and preserves operational safeguards', async () => {
    const { container } = render(VideoSettings);
    await openPanel(container);
    await fireEvent.click(screen.getByLabelText('Apply video spending limits'));
    await fireEvent.click(await screen.findByRole('button', { name: 'Add model estimate' }));
    expect(screen.queryByRole('option', { name: /chat/ })).not.toBeInTheDocument();
    await fireEvent.change(screen.getByLabelText('Video model'), {
      target: { value: 'gemini/veo-3.1-generate-preview' }
    });
    await fireEvent.input(screen.getByLabelText('Estimate (USD)'), { target: { value: '3' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Save limits' }));
    await waitFor(() => expect(calls.savePolicy).toHaveBeenCalledWith({
      ...policy, enabled: true, model_max_cost_usd: { 'gemini/veo-3.1-generate-preview': 3 }
    }));
  });

  it('can disable limits even when an unsaved estimate row is incomplete', async () => {
    const { container } = render(VideoSettings);
    await openPanel(container);
    await fireEvent.click(screen.getByLabelText('Apply video spending limits'));
    await fireEvent.click(await screen.findByRole('button', { name: 'Add model estimate' }));
    await fireEvent.click(screen.getByLabelText('Apply video spending limits'));
    await fireEvent.click(screen.getByRole('button', { name: 'Save limits' }));
    await waitFor(() => expect(calls.savePolicy).toHaveBeenCalledWith(policy));
  });
});
