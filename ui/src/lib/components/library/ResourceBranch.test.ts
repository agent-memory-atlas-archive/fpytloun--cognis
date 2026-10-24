import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ResourceBranch from './ResourceBranch.svelte';
import { libraryQuery, originLabel, type LibraryItem, type LibraryPage } from '$lib/library';

const mocks = vi.hoisted(() => ({ list: vi.fn(), groups: vi.fn() }));
vi.mock('$lib/api/client', () => ({ api: { library: mocks } }));

const item: LibraryItem = {
  id: 'att_branch_upload', title: 'Uploaded brief.txt', kind: 'artifact', format: 'text/plain',
  owner_email: 'reader@cognis.test', agent_id: null, agent_name: null,
  project_id: null, project_name: null, conversation_id: null, conversation_title: null,
  task_id: null, task_title: null, lineage_id: 'att_branch_upload', revision: 1,
  created_at: '2026-10-17T06:00:00Z', updated_at: '2026-10-17T06:00:00Z',
  size_bytes: 128, status: 'attached', origin: 'user', is_readonly: false,
};

describe('Library browsing', () => {
  beforeEach(() => {
    mocks.list.mockReset().mockResolvedValue({ items: [item], next_cursor: null });
    mocks.groups.mockReset().mockResolvedValue({ groups: [{ id: '', label: 'No project', count: 1 }], next_cursor: null });
  });

  it('preserves empty scope IDs and distinguishes upload origins', () => {
    const query = new URLSearchParams(libraryQuery({ kind: 'artifact', project_id: '', conversation_id: '', cursor: undefined }));
    expect(query.has('project_id')).toBe(true);
    expect(query.get('project_id')).toBe('');
    expect(query.has('cursor')).toBe(false);
    expect(originLabel('user')).toBe('User upload');
    expect(originLabel('agent')).toBe('Agent output');
  });

  it('loads folders before their contents and scopes unassigned children', async () => {
    render(ResourceBranch, { filters: { kind: 'artifact' }, levels: ['project'] });
    const folder = await screen.findByRole('button', { name: 'No project 1' });
    expect(mocks.list).not.toHaveBeenCalled();
    await fireEvent.click(folder);
    await screen.findByRole('link', { name: /Uploaded brief/ });
    expect(mocks.list).toHaveBeenCalledWith({ kind: 'artifact', project_id: '' }, undefined);
    expect(screen.getByText('User upload')).toBeInTheDocument();
  });

  it('appends a page and offers recovery after a failed request', async () => {
    mocks.list.mockResolvedValueOnce({ items: [item], next_cursor: 'page-two' }).mockRejectedValueOnce(new Error('Network unavailable'));
    render(ResourceBranch, { filters: { kind: 'artifact' } });
    await fireEvent.click(await screen.findByRole('button', { name: 'Load more resources' }));
    await screen.findByRole('alert');
    expect(screen.getByRole('link', { name: /Uploaded brief/ })).toBeInTheDocument();
    mocks.list.mockResolvedValueOnce({ items: [{ ...item, id: 'art_second_page', title: 'Generated summary' }], next_cursor: null });
    await fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('link', { name: /Generated summary/ })).toBeInTheDocument();
    expect(screen.getAllByRole('link')).toHaveLength(2);
  });

  it('ignores results from an obsolete filter request', async () => {
    let resolve!: (value: LibraryPage) => void;
    mocks.list.mockReturnValueOnce(new Promise<LibraryPage>((done) => { resolve = done; }));
    const view = render(ResourceBranch, { filters: { kind: 'artifact', q: 'old' } });
    await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(1));
    await view.rerender({ filters: { kind: 'artifact', q: 'new' } });
    await screen.findByRole('link', { name: /Uploaded brief/ });
    resolve({ items: [], next_cursor: null });
    await waitFor(() => expect(screen.getByRole('link', { name: /Uploaded brief/ })).toBeInTheDocument());
  });
});
