import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, expectTypeOf, it, vi } from 'vitest';
import type { ComponentProps } from 'svelte';
import SessionDetailsContent, { type SessionDetailsData } from './SessionDetailsContent.svelte';
import type { SessionDetailsProps } from './session-details-types';
import * as loader from './session-details-loader';

vi.mock('$lib/api/client', () => ({
  api: { llmProviders: { providerUsage: vi.fn() } },
}));

const detail: SessionDetailsData = {
  session_id: 'session-a', intaris_session_id: 'intaris-a', intention: null,
  summary: 'Session A', status: 'active', total_calls: 0,
  approved_count: 0, denied_count: 0, escalated_count: 0,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('optional session details loader', () => {
  it('preserves the public props and data type contract', () => {
    expectTypeOf<ComponentProps<typeof SessionDetailsContent>>().toEqualTypeOf<SessionDetailsProps>();
    expectTypeOf<SessionDetailsProps['detail']>().toEqualTypeOf<SessionDetailsData>();
  });

  it('loads only on mount and preserves the mounted body and disclosure state across live props', async () => {
    const load = vi.spyOn(loader, 'loadSessionDetails');
    expect(load).not.toHaveBeenCalled();
    const oldCallback = vi.fn();
    const currentCallback = vi.fn();
    const view = render(SessionDetailsContent, { detail, onOpenIntaris: oldCallback });
    const body = await screen.findByTestId('session-details-content');
    const narrative = screen.getByTestId('session-narrative');
    await fireEvent.click(screen.getByText('Summary'));
    await view.rerender({
      detail: { ...detail, intaris_session_id: 'intaris-b', summary: 'Session B' },
      onOpenIntaris: currentCallback,
    });
    expect(screen.getByTestId('session-details-content')).toBe(body);
    expect(screen.getByTestId('session-narrative')).toBe(narrative);
    expect(narrative).toHaveAttribute('open');
    expect(narrative).toHaveTextContent('Session B');
    await fireEvent.click(screen.getByRole('button', { name: 'Open in Intaris' }));
    expect(currentCallback).toHaveBeenCalledExactlyOnceWith('intaris-b');
    expect(oldCallback).not.toHaveBeenCalled();
    expect(load).toHaveBeenCalledOnce();
  });

  it('uses current owner props when a pending module resolves', async () => {
    const pending = deferred<Awaited<ReturnType<typeof loader.loadSessionDetails>>>();
    vi.spyOn(loader, 'loadSessionDetails').mockReturnValue(pending.promise);
    const oldCallback = vi.fn();
    const currentCallback = vi.fn();
    const view = render(SessionDetailsContent, { detail, onOpenIntaris: oldCallback });
    expect(screen.getByRole('status')).toHaveTextContent('Loading session details');
    await view.rerender({
      detail: { ...detail, session_id: 'session-b', intaris_session_id: 'intaris-b', summary: 'Session B' },
      onOpenIntaris: currentCallback,
    });
    pending.resolve((await import('./SessionDetailsBody.svelte')).default);
    await screen.findByTestId('session-details-content');
    expect(screen.queryByText('session-a')).not.toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: 'Open in Intaris' }));
    expect(currentCallback).toHaveBeenCalledExactlyOnceWith('intaris-b');
    expect(oldCallback).not.toHaveBeenCalled();
  });

  it('does not mount or start provider timers after closing during load', async () => {
    const pending = deferred<Awaited<ReturnType<typeof loader.loadSessionDetails>>>();
    vi.spyOn(loader, 'loadSessionDetails').mockReturnValue(pending.promise);
    const timer = vi.spyOn(window, 'setInterval');
    const view = render(SessionDetailsContent, { detail });
    expect(timer).not.toHaveBeenCalled();
    view.unmount();
    pending.resolve((await import('./SessionDetailsBody.svelte')).default);
    await pending.promise;
    await Promise.resolve();
    expect(screen.queryByTestId('session-details-content')).not.toBeInTheDocument();
    expect(timer).not.toHaveBeenCalled();
  });

  it('offers explicit retry after failure without retaining a rejected attempt', async () => {
    const actualLoad = loader.loadSessionDetails;
    const load = vi.spyOn(loader, 'loadSessionDetails')
      .mockRejectedValueOnce(new Error('Chunk unavailable'))
      .mockImplementation(actualLoad);
    render(SessionDetailsContent, { detail });
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load session details.');
    expect(load).toHaveBeenCalledOnce();
    await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await screen.findByTestId('session-details-content');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it('cleans up mounted provider monitoring on close', async () => {
    const timer = vi.spyOn(window, 'setInterval');
    const clear = vi.spyOn(window, 'clearInterval');
    const view = render(SessionDetailsContent, {
      detail, contextUsage: {
        provider_id: 'provider-a', model: 'model-a', prompt_tokens: 0,
        max_context_tokens: 100, percentage: 0, reasoning_effort: null,
      },
    });
    await screen.findByTestId('session-details-content');
    await waitFor(() => expect(timer).toHaveBeenCalledWith(expect.any(Function), 60_000));
    const index = timer.mock.calls.findIndex((call) => call[1] === 60_000);
    const handle = timer.mock.results[index].value;
    view.unmount();
    expect(clear).toHaveBeenCalledWith(handle);
  });
});
