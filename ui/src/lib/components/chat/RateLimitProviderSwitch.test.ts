import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { chatV2Api } from '$lib/chat-v2/api';
import RateLimitProviderSwitch from './RateLimitProviderSwitch.svelte';

vi.mock('$lib/chat-v2/api', () => ({
  chatV2Api: { retryProviderOptions: vi.fn(), executeCommand: vi.fn() }
}));

const option = { provider_id: 'anthropic-work', display_name: 'Work', model: 'claude-sonnet-4' };
const response = {
  turn_id: 'turn-1', provider_id: 'anthropic-personal', model: option.model, options: [option]
};
const props = {
  conversationId: 'conv-1', turnId: response.turn_id, providerId: response.provider_id,
  model: response.model, retryAt: '2026-10-08T05:00:00Z', onResponse: vi.fn()
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(chatV2Api.retryProviderOptions).mockResolvedValue(response);
});
afterEach(cleanup);

describe('RateLimitProviderSwitch', () => {
  it('switches the exact model with a subtle link and applies the command response', async () => {
    const commandResponse = { result_type: 'system_message', data: { runtime_selection: { provider_id: option.provider_id, model: option.model } } };
    vi.mocked(chatV2Api.executeCommand).mockResolvedValue(commandResponse as never);
    render(RateLimitProviderSwitch, props);
    await fireEvent.click(await screen.findByRole('button', { name: 'Switch to Work' }));
    await waitFor(() => expect(chatV2Api.executeCommand).toHaveBeenCalledWith(
      'conv-1', expect.any(String), '/model anthropic-work/claude-sonnet-4'
    ));
    expect(props.onResponse).toHaveBeenCalledWith(commandResponse);
    expect(chatV2Api.retryProviderOptions).toHaveBeenCalledTimes(2);
  });

  it('uses a native dropdown when several providers are eligible', async () => {
    vi.mocked(chatV2Api.retryProviderOptions).mockResolvedValue({
      ...response, options: [option, { ...option, provider_id: 'anthropic-backup', display_name: 'Backup' }]
    });
    vi.mocked(chatV2Api.executeCommand).mockResolvedValue({ data: {} } as never);
    render(RateLimitProviderSwitch, props);
    const select = await screen.findByRole('combobox', { name: 'Switch provider for the same model' });
    expect(screen.queryByRole('button')).toBeNull();
    await fireEvent.change(select, { target: { value: 'anthropic-backup' } });
    await waitFor(() => expect(chatV2Api.executeCommand).toHaveBeenCalledWith(
      'conv-1', expect.any(String), '/model anthropic-backup/claude-sonnet-4'
    ));
  });

  it('does not switch if the provider became unavailable', async () => {
    vi.mocked(chatV2Api.retryProviderOptions)
      .mockResolvedValueOnce(response)
      .mockResolvedValueOnce({ ...response, options: [] });
    render(RateLimitProviderSwitch, props);
    await fireEvent.click(await screen.findByRole('button', { name: 'Switch to Work' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('no longer available');
    expect(chatV2Api.executeCommand).not.toHaveBeenCalled();
  });

  it('reuses the transaction on uncertain command delivery', async () => {
    vi.mocked(chatV2Api.executeCommand)
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce({ data: {} } as never);
    render(RateLimitProviderSwitch, props);
    await fireEvent.click(await screen.findByRole('button', { name: 'Switch to Work' }));
    await waitFor(() => expect(chatV2Api.executeCommand).toHaveBeenCalledTimes(2));
    expect(vi.mocked(chatV2Api.executeCommand).mock.calls[0])
      .toEqual(vi.mocked(chatV2Api.executeCommand).mock.calls[1]);
  });

  it('ignores options from a previous turn', async () => {
    vi.mocked(chatV2Api.retryProviderOptions).mockResolvedValue({ ...response, turn_id: 'old-turn' });
    render(RateLimitProviderSwitch, props);
    await waitFor(() => expect(chatV2Api.retryProviderOptions).toHaveBeenCalled());
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByRole('combobox')).toBeNull();
  });

  it('keeps recovery available when the command does not switch provider', async () => {
    vi.mocked(chatV2Api.executeCommand).mockResolvedValue({
      result_type: 'system_message', text: 'Provider unavailable', data: {}
    } as never);
    render(RateLimitProviderSwitch, props);
    await fireEvent.click(await screen.findByRole('button', { name: 'Switch to Work' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Provider unavailable');
    expect(screen.getByRole('button', { name: 'Switch to Work' })).toBeVisible();
  });

  it('does not send a command when navigation supersedes preflight', async () => {
    let resolve!: (value: typeof response) => void;
    vi.mocked(chatV2Api.retryProviderOptions)
      .mockResolvedValueOnce(response)
      .mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const view = render(RateLimitProviderSwitch, props);
    await fireEvent.click(await screen.findByRole('button', { name: 'Switch to Work' }));
    await view.rerender({ ...props, conversationId: 'conv-2', turnId: 'turn-2' });
    resolve(response);
    await waitFor(() => expect(screen.queryByRole('status')).toBeNull());
    expect(chatV2Api.executeCommand).not.toHaveBeenCalled();
  });
});
