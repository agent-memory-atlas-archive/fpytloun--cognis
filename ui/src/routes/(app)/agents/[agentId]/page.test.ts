import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import { page } from '$app/stores';
import { api } from '$lib/api/client';
import type { Agent } from '$lib/types/api';
import AgentDetail from './+page.svelte';
import { addToast } from '$lib/stores/toasts';

const navigation = vi.hoisted(() => ({ beforeNavigate: vi.fn(), goto: vi.fn() }));
vi.mock('$app/navigation', () => navigation);
vi.mock('$app/stores', () => ({ page: writable({ params: { agentId: 'editor-agent' } }) }));
vi.mock('$lib/stores/auth', () => {
  const snapshot = { user: { role: 'user', email: 'owner@cognis.local' } };
  return { auth: { ...writable(snapshot), getSnapshot: () => snapshot } };
});
vi.mock('$lib/stores/confirm', () => ({ confirmAction: vi.fn(async () => true) }));
vi.mock('$lib/stores/toasts', () => ({ addToast: vi.fn() }));

function definition(overrides: Partial<Agent> = {}): Agent {
  return {
    agent_id: 'editor-agent', owner_email: 'owner@cognis.local', name: 'Editor agent',
    agent_type: 'primary', status: 'active', personality_synced: true,
    tools: {}, permissions: {}, llm_config: {}, execution: {},
    is_system: false, is_readonly_for_caller: false, is_shared_with_me: false,
    editable_fields: [], agent_profiles: {},
    ...overrides,
  } as Agent;
}

let current: Agent;
beforeEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
  (page as unknown as ReturnType<typeof writable>).set({ params: { agentId: 'editor-agent' } });
  current = definition();
  vi.spyOn(api.agents, 'detail').mockImplementation(async () => current);
  vi.spyOn(api.agents, 'update').mockImplementation(async (_id, payload) => {
    current = { ...current, ...payload } as Agent;
    return current;
  });
  vi.spyOn(api.workflows, 'listAll').mockResolvedValue([]);
  vi.spyOn(api.secrets, 'list').mockResolvedValue([]);
  vi.spyOn(api.credentials, 'list').mockResolvedValue([]);
  vi.spyOn(api.knowledgebases, 'list').mockResolvedValue([]);
  vi.spyOn(api.skills, 'list').mockResolvedValue([]);
  vi.spyOn(api.tools, 'intarisMcpServers').mockResolvedValue([]);
  vi.spyOn(api.agents, 'listAll').mockResolvedValue([]);
  vi.spyOn(api.agents, 'listBindings').mockResolvedValue([]);
  vi.spyOn(api.executor, 'list').mockResolvedValue([]);
  vi.spyOn(api.llmProviders, 'list').mockResolvedValue({ items: [], cursor: null, has_more: false });
  vi.spyOn(api.agents, 'memoryBackends').mockResolvedValue({ items: [] });
  vi.spyOn(api.agents, 'previewEffectiveTools').mockResolvedValue({
    configured_state: { tools: [] },
  } as never);
  vi.spyOn(api.agents, 'listShares').mockResolvedValue([]);
  vi.spyOn(api.projects, 'agentProjects').mockResolvedValue([]);
  vi.spyOn(api.hooks, 'list').mockResolvedValue({ items: [] });
  vi.spyOn(api.hooks, 'assignments').mockResolvedValue({ items: [] });
  vi.spyOn(api.inferenceRoutes, 'list').mockResolvedValue({ routes: [] });
});

async function open() {
  const view = render(AgentDetail);
  await screen.findByPlaceholderText('Research Assistant');
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled());
  return view;
}

describe('agent detail tabs and save boundaries', () => {
  it('shows agent identity before slow configuration registries without exposing an incomplete editor', async () => {
    vi.mocked(api.workflows.listAll).mockReturnValue(new Promise(() => {}));
    render(AgentDetail);
    expect(await screen.findByRole('heading', { name: 'Editor agent' })).toBeVisible();
    expect(screen.queryByPlaceholderText('Research Assistant')).not.toBeInTheDocument();
  });

  it('shows the agent avatar and display name in a compact header without save notices', async () => {
    current = definition({ display_name: 'Research partner', avatar_url: '/agent-photo.png' });
    const { container } = await open();
    const header = container.querySelector('header')!;
    expect(header.querySelector('h1')).toHaveTextContent('Research partner');
    expect(header.querySelector('img')).toHaveAttribute('src', '/agent-photo.png');
    expect(header.querySelector('img')).toHaveAttribute('alt', 'Research partner');
    expect(header).toHaveTextContent('editor-agent');
    expect(screen.queryByText(/Applies immediately|Actions marked/)).not.toBeInTheDocument();
    await fireEvent.error(header.querySelector('img')!);
    expect(header.querySelector('img')).toBeNull();
    expect(header).toHaveTextContent('RP');
  });
  it('confirms successful binding toggles independently of configuration saving', async () => {
    vi.mocked(api.agents.listAll).mockResolvedValue([
      definition({ agent_id: 'delegate-agent', name: 'Delegate agent', agent_type: 'secondary' }),
    ]);
    vi.spyOn(api.agents, 'replaceBindings').mockResolvedValue({} as never);
    await open();
    await fireEvent.click(screen.getByRole('tab', { name: 'Workflows' }));
    await fireEvent.click(screen.getByRole('checkbox', { name: /Delegate agent/ }));
    await waitFor(() => expect(addToast).toHaveBeenCalledWith('Secondary agent bindings saved.', 'success'));
    expect(api.agents.update).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
  });
  it('defers hooks, sharing, project assignments and tool previews until their tabs open', async () => {
    const { container } = await open();
    expect(api.hooks.list).not.toHaveBeenCalled();
    expect(api.agents.listShares).not.toHaveBeenCalled();
    expect(api.projects.agentProjects).not.toHaveBeenCalled();
    expect(api.agents.previewEffectiveTools).not.toHaveBeenCalled();
    expect(screen.queryByRole('heading', { name: 'Project assignments' })).not.toBeInTheDocument();
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
    await fireEvent.click(screen.getByRole('tab', { name: 'Collaboration' }));
    await screen.findByRole('heading', { name: 'Project assignments' });
    expect(api.projects.agentProjects).toHaveBeenCalledOnce();
    expect(api.agents.listShares).toHaveBeenCalledOnce();
    expect(container.querySelector('form form')).toBeNull();
    await fireEvent.click(screen.getByRole('tab', { name: 'Hooks' }));
    await screen.findByText('No hooks assigned. Choose a bundled hook or create your own.');
    expect(api.hooks.list).toHaveBeenCalledOnce();
    await fireEvent.click(screen.getByRole('tab', { name: 'Identity' }));
    await fireEvent.click(screen.getByRole('tab', { name: 'Hooks' }));
    expect(api.hooks.list).toHaveBeenCalledOnce();
    expect(container.querySelectorAll('[role="tabpanel"]:not([hidden])')).toHaveLength(1);
  });

  it('keeps configuration drafts through immediate status changes and saves without remounting', async () => {
    vi.spyOn(api.agents, 'suspend').mockImplementation(async () => {
      current = { ...current, status: 'suspended' };
      return current;
    });
    await open();
    const input = screen.getByPlaceholderText('Research Assistant');
    await fireEvent.input(input, { target: { value: 'Unsaved identity' } });
    expect(api.agents.update).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole('button', { name: 'Suspend' }));
    await screen.findByRole('button', { name: 'Activate' });
    expect(input).toHaveValue('Unsaved identity');
    await fireEvent.click(screen.getByRole('tab', { name: 'Hooks' }));
    await screen.findByText('No hooks assigned. Choose a bundled hook or create your own.');
    await fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled());
    expect(api.agents.update).toHaveBeenCalledWith('editor-agent', expect.objectContaining({ name: 'Unsaved identity' }));
    expect(screen.getByRole('tab', { name: 'Hooks' })).toHaveAttribute('aria-selected', 'true');
    expect(api.hooks.list).toHaveBeenCalledOnce();
  });

  it('keeps edits made while saving dirty instead of overwriting them with the response', async () => {
    let complete!: (agent: Agent) => void;
    vi.mocked(api.agents.update).mockImplementation(() => new Promise(resolve => { complete = resolve; }));
    await open();
    const input = screen.getByPlaceholderText('Research Assistant');
    await fireEvent.input(input, { target: { value: 'Submitted identity' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await fireEvent.input(input, { target: { value: 'Newer identity' } });
    complete({ ...current, name: 'Submitted identity' });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled());
    expect(input).toHaveValue('Newer identity');
    expect(screen.getByText('Unsaved configuration changes')).toBeVisible();
  });

  it('shows retryable project and tool errors rather than empty success states', async () => {
    vi.mocked(api.projects.agentProjects).mockRejectedValueOnce(new Error('Projects unavailable'));
    vi.mocked(api.agents.previewEffectiveTools).mockRejectedValueOnce(new Error('Tools unavailable'));
    await open();
    await fireEvent.click(screen.getByRole('tab', { name: 'Collaboration' }));
    await screen.findByRole('button', { name: 'Retry loading projects' });
    expect(screen.queryByText('Not assigned to any project.')).not.toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: 'Retry loading projects' }));
    await screen.findByText('Not assigned to any project.');
    await fireEvent.click(screen.getByRole('tab', { name: 'Tools' }));
    await screen.findByRole('button', { name: 'Retry loading tools' });
    await fireEvent.click(screen.getByRole('button', { name: 'Retry loading tools' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Retry loading tools' })).toBeNull());
    expect(api.agents.previewEffectiveTools).toHaveBeenCalledTimes(2);
  });

  it('does not mark untouched configuration dirty when visiting lazy panels', async () => {
    vi.mocked(api.agents.previewEffectiveTools).mockResolvedValue({
      configured_state: { tools: [
        { name: 'read', tool_id: 'read', category: 'filesystem', description: 'Read files', source: { type: 'builtin' } },
        { name: 'inspect', tool_id: 'mcp:inspect', category: 'mcp', description: 'Inspect service', source: { type: 'local_mcp', server_id: 'service', server_name: 'Service' } },
      ] },
    } as never);
    current = definition({
      execution: { executor_id: 'retired-executor' },
      llm_config: { provider_id: 'retired-provider', model: 'retired-model' },
    });
    await open();
    for (const name of ['Providers & models', 'Access & delegation', /^Profiles/, 'Workflows', 'Tools']) {
      await fireEvent.click(screen.getByRole('tab', { name }));
      if (name === 'Tools') await screen.findByRole('searchbox');
      await waitFor(() => expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled());
    }
    await fireEvent.input(screen.getByRole('searchbox'), { target: { value: 'read' } });
    const permission = screen.getByRole('combobox', { name: 'Permission for read' });
    await fireEvent.change(permission, { target: { value: 'deny' } });
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled();
    await fireEvent.change(permission, { target: { value: '' } });
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
    await fireEvent.click(screen.getByRole('tab', { name: 'Identity' }));
    await fireEvent.input(screen.getByPlaceholderText('Research Assistant'), { target: { value: 'Rename only' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(api.agents.update).toHaveBeenCalledWith('editor-agent', expect.objectContaining({
      execution: expect.objectContaining({ executor_id: 'retired-executor' }),
      llm_config: expect.objectContaining({ provider_id: 'retired-provider', model: 'retired-model' }),
    }));
  });

  it('keeps failed immediate bindings unchecked and does not mix them into configuration save', async () => {
    vi.mocked(api.agents.listAll).mockResolvedValue([
      definition({ agent_id: 'delegate-agent', name: 'Delegate agent', agent_type: 'secondary' }),
    ]);
    vi.spyOn(api.agents, 'replaceBindings').mockRejectedValue(new Error('Binding rejected'));
    await open();
    await fireEvent.click(screen.getByRole('tab', { name: 'Workflows' }));
    const binding = screen.getByRole('checkbox', { name: /Delegate agent/ });
    await fireEvent.click(binding);
    await screen.findByText('Binding rejected');
    expect(binding).not.toBeChecked();
    expect(api.agents.update).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
  });

  it('keeps system overrides dirty through immediate enable/disable', async () => {
    current = definition({ is_system: true, disableable: true, editable_fields: ['llm_config.model'] });
    vi.spyOn(api.agents, 'disableSystem').mockImplementation(async () => {
      current = { ...current, disabled: true };
      return current;
    });
    render(AgentDetail);
    await screen.findByRole('button', { name: 'Disable' });
    expect(screen.queryByRole('tab', { name: 'Hooks' })).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Collaboration' })).not.toBeInTheDocument();
    await fireEvent.click(screen.getByRole('tab', { name: 'Providers & models' }));
    await fireEvent.input(screen.getByPlaceholderText('Use provider default'), { target: { value: 'New model' } });
    await fireEvent.click(screen.getByRole('tab', { name: 'Identity' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Disable' }));
    await screen.findByRole('button', { name: 'Enable' });
    await fireEvent.click(screen.getByRole('tab', { name: 'Providers & models' }));
    expect(screen.getByPlaceholderText('Use provider default')).toHaveValue('New model');
    expect(screen.getByRole('button', { name: 'Save overrides' })).toBeEnabled();
  });

  it('keeps shared configuration read-only while allowing an independent executor save', async () => {
    current = definition({ is_shared_with_me: true, is_readonly_for_caller: true });
    const grant = { executor_scope: 'grantee_executor', grantee_overrides: { execution: {} } };
    vi.spyOn(api.agents, 'myShare').mockResolvedValue(grant as never);
    vi.spyOn(api.agents, 'updateMyShare').mockResolvedValue(grant as never);
    render(AgentDetail);
    await screen.findByPlaceholderText('Research Assistant');
    expect(screen.queryByRole('button', { name: 'Save changes' })).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Hooks' })).not.toBeInTheDocument();
    await fireEvent.click(screen.getByRole('tab', { name: 'Access & delegation' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Save executor' }));
    await waitFor(() => expect(api.agents.updateMyShare).toHaveBeenCalledOnce());
    expect(api.agents.update).not.toHaveBeenCalled();
  });

  it('resets tab state when client navigation selects another agent', async () => {
    await open();
    await fireEvent.click(screen.getByRole('tab', { name: 'Hooks' }));
    await screen.findByText('No hooks assigned. Choose a bundled hook or create your own.');
    current = definition({ agent_id: 'other-agent', name: 'Other agent' });
    (page as unknown as ReturnType<typeof writable>).set({ params: { agentId: 'other-agent' } });
    await screen.findByRole('heading', { name: 'Other agent' });
    expect(await screen.findByRole('tab', { name: 'Identity' })).toHaveAttribute('aria-selected', 'true');
    expect(api.agents.detail).toHaveBeenLastCalledWith('other-agent');
    expect(api.hooks.list).toHaveBeenCalledOnce();
  });
});
