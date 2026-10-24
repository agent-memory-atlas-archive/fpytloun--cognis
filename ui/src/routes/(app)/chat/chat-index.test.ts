import { render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  goto: vi.fn(async () => undefined),
  listAll: vi.fn(),
  open: vi.fn(),
  resolve: vi.fn(),
  navigated: new Set<() => void>(),
}));

vi.mock('$app/navigation', async () => {
  const { onMount } = await import('svelte');
  return {
    goto: mocks.goto,
    afterNavigate: (callback: () => void) => onMount(() => {
      mocks.navigated.add(callback);
      callback();
      return () => { mocks.navigated.delete(callback); };
    }),
  };
});
vi.mock('$lib/api/client', () => ({
  api: {
    agents: { listAll: mocks.listAll },
    conversations: { open: mocks.open, resolve: mocks.resolve },
  },
}));

import ChatIndexPage from './+page.svelte';

const LAST_OPENED_KEY = 'cognis-chat-last-opened-conversation';

function agent(agentId: string, status = 'active') {
  return { agent_id: agentId, agent_type: 'primary', status };
}

function conversation(conversationId: string, agentId: string) {
  return { conversation_id: conversationId, agent_id: agentId, agent_profile_id: null, context: { type: 'web' } };
}

describe('chat index default conversation', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    mocks.goto.mockClear();
    mocks.listAll.mockReset();
    mocks.open.mockReset();
    mocks.resolve.mockReset();
    window.history.replaceState(null, '', '/chat');
  });

  afterEach(() => {
    window.localStorage.clear();
    window.history.replaceState(null, '', '/chat');
  });

  it('opens the last-opened conversation in parallel with the agent list', async () => {
    window.localStorage.setItem(LAST_OPENED_KEY, JSON.stringify({
      conversation_id: 'conv_last', agent_id: 'riker', opened_at: new Date().toISOString(),
    }));
    let resolveAgents!: (value: unknown) => void;
    mocks.listAll.mockReturnValue(new Promise((resolve) => { resolveAgents = resolve; }));
    mocks.open.mockResolvedValue(conversation('conv_last', 'riker'));

    render(ChatIndexPage);

    await waitFor(() => expect(mocks.open).toHaveBeenCalledTimes(1));
    expect(mocks.open.mock.calls[0][0]).toMatchObject({ agent_id: 'riker' });
    resolveAgents([agent('riker')]);

    await waitFor(() => expect(mocks.goto).toHaveBeenCalledWith('/chat/conv_last', { replaceState: true }));
    expect(mocks.open).toHaveBeenCalledTimes(1);
  });

  it('discards the speculative open when the last agent is no longer active', async () => {
    window.localStorage.setItem(LAST_OPENED_KEY, JSON.stringify({
      conversation_id: 'conv_old', agent_id: 'retired', opened_at: new Date().toISOString(),
    }));
    mocks.listAll.mockResolvedValue([agent('retired', 'disabled'), agent('riker')]);
    mocks.open.mockImplementation(async (request: { agent_id: string }) => (
      conversation(request.agent_id === 'riker' ? 'conv_riker' : 'conv_old', request.agent_id)
    ));

    render(ChatIndexPage);

    await waitFor(() => expect(mocks.goto).toHaveBeenCalledWith('/chat/conv_riker', { replaceState: true }));
    expect(mocks.open.mock.calls.map(([request]) => request.agent_id)).toEqual(['retired', 'riker']);
  });

  it('uses the sequential path without a last-opened entry', async () => {
    mocks.listAll.mockResolvedValue([agent('riker')]);
    mocks.open.mockResolvedValue(conversation('conv_new', 'riker'));

    render(ChatIndexPage);

    await waitFor(() => expect(mocks.goto).toHaveBeenCalledWith('/chat/conv_new', { replaceState: true }));
    expect(mocks.open).toHaveBeenCalledTimes(1);
  });
  it('opens the requested main agent conversation instead of restoring a different recent topic', async () => {
    window.history.replaceState(null, '', '/chat?agent_id=laforge&scope=agent_direct');
    window.localStorage.setItem(LAST_OPENED_KEY, JSON.stringify({
      conversation_id: 'conv_last', agent_id: 'riker', opened_at: new Date().toISOString(),
    }));
    mocks.resolve.mockResolvedValue(conversation('conv_main', 'laforge'));
    render(ChatIndexPage);
    await waitFor(() => expect(mocks.goto).toHaveBeenCalledWith('/chat/conv_main', { replaceState: true }));
    expect(mocks.resolve).toHaveBeenCalledWith({ agent_id: 'laforge', context_type: 'web', scope: 'agent_direct' });
    expect(mocks.listAll).not.toHaveBeenCalled();
    expect(mocks.open).not.toHaveBeenCalled();
  });
  it('does not fall back to an unrelated conversation when direct access fails', async () => {
    window.history.replaceState(null, '', '/chat?agent_id=laforge&scope=agent_direct');
    mocks.resolve.mockRejectedValue(new Error('Access denied'));
    const view = render(ChatIndexPage);
    await view.findByText('Access denied');
    expect(mocks.goto).not.toHaveBeenCalled();
    expect(mocks.open).not.toHaveBeenCalled();
  });
  it('does not redirect away from the next page when a main-agent resolution finishes late', async () => {
    window.history.replaceState(null, '', '/chat?agent_id=laforge&scope=agent_direct');
    let finish!: (value: ReturnType<typeof conversation>) => void;
    const pending = new Promise<ReturnType<typeof conversation>>(resolve => { finish = resolve; });
    mocks.resolve.mockReturnValue(pending);
    const view = render(ChatIndexPage);
    await waitFor(() => expect(mocks.resolve).toHaveBeenCalledTimes(1));
    view.unmount();
    finish(conversation('conv_main', 'laforge'));
    await Promise.resolve(); await Promise.resolve();
    expect(mocks.goto).not.toHaveBeenCalled();
  });
  it('resolves a changed main-agent query and fences the previous request on the same mounted page', async () => {
    window.history.replaceState(null, '', '/chat?agent_id=laforge&scope=agent_direct');
    let finishA!: (value: ReturnType<typeof conversation>) => void;
    let finishB!: (value: ReturnType<typeof conversation>) => void;
    const a = new Promise<ReturnType<typeof conversation>>(resolve => { finishA = resolve; });
    const b = new Promise<ReturnType<typeof conversation>>(resolve => { finishB = resolve; });
    mocks.resolve.mockImplementation(({ agent_id }) => agent_id === 'laforge' ? a : b);
    render(ChatIndexPage);
    await waitFor(() => expect(mocks.resolve).toHaveBeenCalledTimes(1));
    window.history.replaceState(null, '', '/chat?agent_id=riker&scope=agent_direct');
    mocks.navigated.forEach(callback => callback());
    await waitFor(() => expect(mocks.resolve).toHaveBeenCalledTimes(2));
    finishA(conversation('conv_a', 'laforge'));
    await Promise.resolve(); await Promise.resolve();
    expect(mocks.goto).not.toHaveBeenCalled();
    expect(window.localStorage.getItem(LAST_OPENED_KEY)).toBeNull();
    finishB(conversation('conv_b', 'riker'));
    await waitFor(() => expect(mocks.goto).toHaveBeenCalledWith('/chat/conv_b', { replaceState: true }));
    expect(mocks.goto).toHaveBeenCalledTimes(1);
    expect(JSON.parse(window.localStorage.getItem(LAST_OPENED_KEY)!).conversation_id).toBe('conv_b');
  });
});
