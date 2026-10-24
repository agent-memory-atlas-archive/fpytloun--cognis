import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';
import { api } from '$lib/api/client';
import { page } from '$app/stores';
import { syncHealthWorkflow } from '$lib/testing/workflow-plan-fixture';
import Workflows from './+page.svelte';

vi.mock('$app/navigation', () => ({ beforeNavigate: vi.fn() }));
vi.mock('$app/stores', () => ({ page: writable({ url: new URL('http://localhost/workflows') }) }));
vi.mock('$lib/stores/toasts', () => ({ addToast: vi.fn() }));

beforeEach(() => {
  vi.restoreAllMocks();
  (page as unknown as ReturnType<typeof writable>).set({ url: new URL('http://localhost/workflows') });
  vi.spyOn(api.workflows, 'listAll').mockResolvedValue([syncHealthWorkflow()]);
  vi.spyOn(api.workflows, 'stepProfiles').mockResolvedValue([]);
  vi.spyOn(api.agents, 'listAll').mockResolvedValue([]);
});
afterEach(cleanup);

describe('workflow page loading', () => {
  it('renders the registry before step profiles without exposing an incomplete editor', async () => {
    vi.mocked(api.workflows.stepProfiles).mockReturnValue(new Promise(() => {}));
    render(Workflows);
    expect(await screen.findByRole('button', { name: new RegExp(syncHealthWorkflow().name) })).toBeDisabled();
    expect(screen.queryByPlaceholderText('wf_review_loop')).not.toBeInTheDocument();
  });

  it('keeps the registry after a profile failure and retries configuration safely', async () => {
    vi.mocked(api.workflows.stepProfiles).mockRejectedValueOnce(new Error('Profiles unavailable'));
    render(Workflows);
    expect(await screen.findByRole('alert')).toHaveTextContent('Profiles unavailable');
    expect(screen.getByRole('button', { name: new RegExp(syncHealthWorkflow().name) })).toBeInTheDocument();
    expect(screen.queryByPlaceholderText('wf_review_loop')).not.toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: 'Retry workflow profiles' }));
    await screen.findByPlaceholderText('wf_review_loop');
  });

  it('resumes a requested draft after retrying profile metadata', async () => {
    (page as unknown as ReturnType<typeof writable>).set({
      url: new URL('http://localhost/workflows?draftFrom=sync-health')
    });
    const source = { ...syncHealthWorkflow(), name: 'Recovered draft' };
    vi.spyOn(api.workflows, 'detail').mockResolvedValue(source);
    vi.mocked(api.workflows.stepProfiles).mockRejectedValueOnce(new Error('Profiles unavailable'));
    render(Workflows);
    await fireEvent.click(await screen.findByRole('button', { name: 'Retry workflow profiles' }));
    await screen.findByDisplayValue('Recovered draft Copy');
    expect(api.workflows.detail).toHaveBeenCalledWith('sync-health');
  });
});
