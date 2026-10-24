import { cleanup, render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import Chat from './+page.svelte';

const mocks = vi.hoisted(() => ({
  goto: vi.fn(),
  afterNavigate: vi.fn(),
  listAll: vi.fn(),
  open: vi.fn(),
  resolve: vi.fn(),
}));
vi.mock('$app/navigation', () => ({
  goto: mocks.goto,
  afterNavigate: mocks.afterNavigate,
}));
vi.mock('$lib/api/client', () => ({
  api: {
    agents: { listAll: mocks.listAll },
    conversations: { open: mocks.open, resolve: mocks.resolve },
  },
}));

beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  window.history.replaceState({}, '', '/chat');
  mocks.listAll.mockResolvedValue([{ agent_id: 'laforge', agent_type: 'primary', status: 'active' }]);
  mocks.open.mockResolvedValue({ conversation_id: 'restored-chat', agent_id: 'laforge' });
  mocks.resolve.mockResolvedValue({ conversation_id: 'direct-chat', agent_id: 'laforge' });
  mocks.goto.mockResolvedValue(undefined);
});
afterEach(cleanup);

it('opens chat when auth and storage readiness mount the page after navigation completed', async () => {
  // No afterNavigate callback: SvelteKit already finished navigating while
  // the parent layout was waiting for authentication and device storage.
  render(Chat);
  await waitFor(() => expect(mocks.goto).toHaveBeenCalledWith('/chat/restored-chat', { replaceState: true }));
  expect(mocks.listAll).toHaveBeenCalledOnce();
  expect(mocks.open).toHaveBeenCalledOnce();
});

it('does not resolve twice when navigation also reports the initial location', async () => {
  render(Chat);
  await waitFor(() => expect(mocks.open).toHaveBeenCalledOnce());
  mocks.afterNavigate.mock.calls[0][0]();
  await waitFor(() => expect(mocks.goto).toHaveBeenCalledOnce());
  expect(mocks.listAll).toHaveBeenCalledOnce();
  expect(mocks.open).toHaveBeenCalledOnce();
});

it('resolves a changed main-agent request when SvelteKit reuses the page', async () => {
  render(Chat);
  await waitFor(() => expect(mocks.goto).toHaveBeenCalledOnce());
  window.history.replaceState({}, '', '/chat?scope=agent_direct&agent_id=laforge');
  mocks.afterNavigate.mock.calls[0][0]();
  await waitFor(() => expect(mocks.resolve).toHaveBeenCalledWith({
    agent_id: 'laforge', context_type: 'web', scope: 'agent_direct',
  }));
  await waitFor(() => expect(mocks.goto).toHaveBeenLastCalledWith('/chat/direct-chat', { replaceState: true }));
});

it('does not navigate with a resolution that finishes after unmount', async () => {
  let resolve!: (agents: unknown[]) => void;
  mocks.listAll.mockReturnValue(new Promise((done) => { resolve = done; }));
  const view = render(Chat);
  await waitFor(() => expect(mocks.listAll).toHaveBeenCalledOnce());
  view.unmount();
  resolve([{ agent_id: 'laforge', agent_type: 'primary', status: 'active' }]);
  await Promise.resolve();
  expect(mocks.open).not.toHaveBeenCalled();
  expect(mocks.goto).not.toHaveBeenCalled();
});
