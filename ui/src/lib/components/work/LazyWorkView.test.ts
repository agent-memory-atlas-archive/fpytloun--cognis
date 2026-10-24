import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { conversationTimelineScope, type WorkProjectionResponse } from '$lib/chat-v2/types';
import { clearWorkViewStates } from '$lib/work/workViewState';
import LazyWorkView from './LazyWorkView.svelte';
import WorkView from './WorkView.svelte';
import * as loader from './work-view-loader';

const scope = conversationTimelineScope('lazy-work-fixture');
const projection: WorkProjectionResponse = {
  schema_version: 2, projection_version: 'test', scope,
  mutations: [], commands: [], artifacts: [],
  summary: { mutations: 0, commands: 0, changed_files: 0, artifacts: 0 },
  has_more_before: false, server_time: '',
};
afterEach(() => { cleanup(); clearWorkViewStates(); vi.restoreAllMocks(); });

describe('optional Work inspector module boundary', () => {
  it('does not request Work data until loaded and forwards the latest tab/focus props', async () => {
    let resolve!: (view: typeof WorkView) => void;
    const pending = new Promise<typeof WorkView>(done => { resolve = done; });
    vi.spyOn(loader, 'loadWorkView').mockReturnValue(pending);
    const loadWork = vi.fn().mockResolvedValue(projection);
    const view = render(LazyWorkView, { scope, initialTab: 'commands', forceInitialTab: true, loadWork, refreshIntervalMs: 0 });
    expect(screen.getByRole('status')).toHaveTextContent('Loading Work inspector');
    expect(loadWork).not.toHaveBeenCalled();
    await view.rerender({ scope, initialTab: 'files', forceInitialTab: true, loadWork, refreshIntervalMs: 0 });
    resolve(WorkView);
    await waitFor(() => expect(loadWork).toHaveBeenCalled());
    expect(await screen.findByTestId('work-tab-files')).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByText('Loading Work inspector…')).toBeNull();
  });

  it('keeps an actionable retry after module failure without moving focus out of the inspector', async () => {
    vi.spyOn(loader, 'loadWorkView')
      .mockRejectedValueOnce(new Error('Synthetic module load failure'))
      .mockResolvedValueOnce(WorkView);
    const loadWork = vi.fn().mockResolvedValue(projection);
    render(LazyWorkView, { scope, loadWork, refreshIntervalMs: 0 });
    await screen.findByRole('alert');
    const retry = screen.getByRole('button', { name: 'Try again' });
    retry.focus();
    expect(document.activeElement).toBe(retry);
    await fireEvent.click(retry);
    expect(await screen.findByTestId('work-tab-files')).toBeInTheDocument();
    expect(loader.loadWorkView).toHaveBeenCalledTimes(2);
    expect(loadWork).toHaveBeenCalledTimes(1);
  });

  it('does not mount or request Work after closing during module loading; a later open still works', async () => {
    let resolve!: (view: typeof WorkView) => void;
    const pending = new Promise<typeof WorkView>(done => { resolve = done; });
    vi.spyOn(loader, 'loadWorkView').mockReturnValue(pending);
    const loadWork = vi.fn().mockResolvedValue(projection);
    const view = render(LazyWorkView, { scope, loadWork, refreshIntervalMs: 0 });
    view.unmount();
    resolve(WorkView);
    await Promise.resolve();
    expect(loadWork).not.toHaveBeenCalled();
    render(LazyWorkView, { scope, loadWork, refreshIntervalMs: 0 });
    expect(await screen.findByTestId('work-tab-files')).toBeInTheDocument();
    await waitFor(() => expect(loadWork).toHaveBeenCalledTimes(1));
  });
});
