import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { defaultModelEntry } from '$lib/types/api';
import { INSTANCE_MANAGEMENT_TOOLS, INSTANCE_MANAGEMENT_SKILLS } from '$lib/instance-management';

const { api, goto } = vi.hoisted(() => ({
  goto: vi.fn().mockResolvedValue(undefined),
  api: {
    llmProviders: { list: vi.fn(), create: vi.fn(), test: vi.fn(), discoverModelsPreview: vi.fn(), startChatgptOAuth: vi.fn(), chatgptOAuthStatus: vi.fn(), discoverModels: vi.fn(), update: vi.fn() },
    modelRouting: { get: vi.fn(), update: vi.fn() },
    secrets: { upsert: vi.fn() },
    executor: { list: vi.fn(), create: vi.fn(), generateToken: vi.fn() },
    skills: { list: vi.fn() }, workflows: { list: vi.fn() },
    agents: { listAll: vi.fn(), create: vi.fn() },
    system: { finishOnboarding: vi.fn(), diagnostics: vi.fn() }, conversations: { resolve: vi.fn() }
  }
}));
vi.mock('$lib/api/client', () => ({ api, asApiError: (error: Error) => error }));
vi.mock('$app/navigation', () => ({ goto }));
vi.mock('$lib/stores/auth', () => ({ auth: { getSnapshot: () => ({ user: { email: 'owner@cognis.localdev.me' } }) } }));

import OnboardingModels from './OnboardingModels.svelte';
import OnboardingExecutor from './OnboardingExecutor.svelte';
import OnboardingAgent from './OnboardingAgent.svelte';
import { saveSetupDraft } from '$lib/onboarding-setup';

const provider = {
  provider_id: 'openrouter-starter', display_name: 'OpenRouter', status: 'active',
  owner_email: 'system@cognis.local', config: { preset: 'openrouter' },
  models: [
    defaultModelEntry('openai/gpt-oss-20b'), defaultModelEntry('openai/gpt-oss-120b'),
    { ...defaultModelEntry('openai/text-embedding-3-small'), supports_embedding: true }
  ]
};
const readyExecutor = {
  executor_id: 'my-computer', name: 'My computer', available: true, status: 'active',
  runtime_state: 'active', desired_config_version: 2, applied_config_version: 2, observed_tools: ['list_directory']
};

beforeEach(() => {
  cleanup(); localStorage.clear(); vi.clearAllMocks();
  api.llmProviders.list.mockResolvedValue({ items: [] });
  api.llmProviders.discoverModelsPreview.mockResolvedValue({ models: provider.models });
  api.llmProviders.create.mockResolvedValue(provider);
  api.llmProviders.test.mockResolvedValue({ ok: true });
  api.llmProviders.update.mockImplementation(async (id, payload) => ({ ...provider, ...payload, provider_id: id, models: payload.config?.models ?? provider.models }));
  api.llmProviders.chatgptOAuthStatus.mockResolvedValue({ status: 'pending' });
  api.llmProviders.discoverModels.mockResolvedValue({ models: provider.models });
  api.secrets.upsert.mockResolvedValue({});
  api.modelRouting.get.mockResolvedValue({});
  api.modelRouting.update.mockImplementation(async (routes) => routes);
  api.executor.list.mockResolvedValue([]);
  api.skills.list.mockResolvedValue(INSTANCE_MANAGEMENT_SKILLS.map((skill_id) => ({ skill_id })));
  api.workflows.list.mockResolvedValue({ items: [] });
  api.agents.listAll.mockResolvedValue([]);
  api.agents.create.mockImplementation(async (payload) => ({
    ...payload, name: 'Ari', owner_email: 'owner@cognis.localdev.me'
  }));
  api.system.finishOnboarding.mockResolvedValue({});
  api.conversations.resolve.mockResolvedValue({ conversation_id: 'first-direct-chat' });
});

describe('three-step setup boundaries', () => {
  it('starts with extensible system preset cards and keeps optional agent shortcuts visible', async () => {
    render(OnboardingModels, { onChanged: vi.fn(), onContinue: vi.fn() });
    expect(await screen.findByRole('button', { name: /OpenRouter Recommended/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Custom \(advanced\)/ })).toBeTruthy();
    expect(screen.queryByLabelText('OpenRouter API key')).toBeNull();
    expect(screen.getByRole('button', { name: /Codex Use your ChatGPT/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /OpenAI Connect with an API/ })).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: /OpenAI Connect with an API/ }));
    expect(screen.getByLabelText('OpenAI API key')).toBeTruthy();
    expect(api.llmProviders.create).not.toHaveBeenCalled();
  });
  it('validates and saves an optional private API provider without changing system routes', async () => {
    const onChanged = vi.fn().mockResolvedValue(undefined);
    render(OnboardingModels, { onChanged, onContinue: vi.fn() });
    await fireEvent.click(await screen.findByRole('button', { name: /Anthropic Connect Claude/ }));
    await fireEvent.input(screen.getByLabelText('Anthropic API key'), { target: { value: 'local-test-key' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Connect provider' }));
    await waitFor(() => expect(api.llmProviders.update).toHaveBeenCalled());
    expect(api.llmProviders.create.mock.calls[0][0].config.scope).toBe('user');
    expect(api.secrets.upsert.mock.calls[0][0].scope).toBe('user');
    expect(api.llmProviders.test).toHaveBeenCalled();
    expect(api.modelRouting.update).not.toHaveBeenCalled();
  });
  it('persists discovered Codex models only after successful subscription sign-in', async () => {
    const codex = { ...provider, provider_id: 'codex-account', owner_email: 'owner@cognis.localdev.me', config: { preset: 'chatgpt' }, models: [] };
    api.llmProviders.create.mockResolvedValue(codex);
    api.llmProviders.startChatgptOAuth.mockResolvedValue({ status: 'pending', verification_url: 'https://auth.openai.com/codex/device', user_code: '1234-5678' });
    api.llmProviders.chatgptOAuthStatus.mockResolvedValue({ status: 'authorized' });
    render(OnboardingModels, { onChanged: vi.fn(), onContinue: vi.fn() });
    await fireEvent.click(await screen.findByRole('button', { name: /Codex Use your ChatGPT/ }));
    await fireEvent.click(screen.getByRole('button', { name: 'Sign in with ChatGPT' }));
    await screen.findByText('1234-5678');
    expect(api.llmProviders.discoverModels).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole('button', { name: 'Check sign-in' }));
    await waitFor(() => expect(api.llmProviders.update).toHaveBeenCalledWith('codex-account', expect.any(Object)));
    expect(api.modelRouting.update).not.toHaveBeenCalled();
  });
  it('never reuses or authorizes a global Codex provider for the private shortcut', async () => {
    const globalCodex = { ...provider, provider_id: 'shared-codex', config: { preset: 'chatgpt' } };
    const privateCodex = { ...provider, provider_id: 'my-codex', owner_email: 'owner@cognis.localdev.me', config: { preset: 'chatgpt' }, models: [] };
    api.llmProviders.list.mockResolvedValue({ items: [globalCodex] });
    api.llmProviders.create.mockResolvedValue(privateCodex);
    api.llmProviders.startChatgptOAuth.mockResolvedValue({ status: 'pending', verification_url: 'https://auth.openai.com/codex/device', user_code: '1234-5678' });
    render(OnboardingModels, { onChanged: vi.fn(), onContinue: vi.fn() });
    await fireEvent.click(await screen.findByRole('button', { name: /Codex Use your ChatGPT/ }));
    await fireEvent.click(screen.getByRole('button', { name: 'Sign in with ChatGPT' }));
    await waitFor(() => expect(api.llmProviders.startChatgptOAuth).toHaveBeenCalledWith('my-codex'));
    expect(api.llmProviders.create.mock.calls[0][0].config.scope).toBe('user');
    expect(api.llmProviders.chatgptOAuthStatus).not.toHaveBeenCalled();
    expect(api.llmProviders.update).not.toHaveBeenCalled();
  });
  it('does not label a failed private API account connected or suppress its form', async () => {
    api.llmProviders.list.mockResolvedValue({ items: [{ ...provider, provider_id: 'failed-account',
      owner_email: 'owner@cognis.localdev.me', config: { preset: 'openai' }, last_test: { ok: false } }] });
    render(OnboardingModels, { onChanged: vi.fn(), onContinue: vi.fn() });
    const card = await screen.findByRole('button', { name: /OpenAI Connect with an API/ });
    expect(card.querySelector('[aria-label="Configured"]')).toBeNull();
    await fireEvent.click(card);
    expect(screen.getByLabelText('OpenAI API key')).toBeTruthy();
    expect(screen.queryByText(/Connected. Available/)).toBeNull();
  });
  it('retries a rejected optional account test without creating a duplicate provider', async () => {
    const privateProvider = { ...provider, provider_id: 'private-openai', owner_email: 'owner@cognis.localdev.me',
      config: { preset: 'openai', auth_config: { mode: 'secret', secret_name: 'private-openai-key' } }, status: 'draft' };
    api.llmProviders.create.mockResolvedValue(privateProvider);
    api.llmProviders.test.mockResolvedValueOnce({ ok: false, error_detail: 'Authentication rejected' }).mockResolvedValue({ ok: true });
    render(OnboardingModels, { onChanged: vi.fn(), onContinue: vi.fn() });
    await fireEvent.click(await screen.findByRole('button', { name: /OpenAI Connect with an API/ }));
    await fireEvent.input(screen.getByLabelText('OpenAI API key'), { target: { value: 'local-test-key' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Connect provider' }));
    await screen.findByText('Authentication rejected');
    await fireEvent.click(screen.getByRole('button', { name: 'Connect provider' }));
    await waitFor(() => expect(api.llmProviders.update).toHaveBeenCalled());
    expect(api.llmProviders.create).toHaveBeenCalledOnce();
    expect(api.secrets.upsert).toHaveBeenLastCalledWith(expect.objectContaining({ name: 'private-openai-key', scope: 'user' }));
    expect(api.modelRouting.update).not.toHaveBeenCalled();
  });
  it('does not advance custom setup until all required system routes are configured', async () => {
    api.llmProviders.list.mockResolvedValue({ items: [provider] });
    api.system.diagnostics.mockResolvedValue({ readiness: { agent_model_configured: true, companion_routes_configured: false } });
    const onContinue = vi.fn();
    render(OnboardingModels, { onChanged: vi.fn(), onContinue });
    await fireEvent.click(await screen.findByRole('button', { name: /Custom \(advanced\)/ }));
    await fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await screen.findByText('Finish configuring the required system and default agent models before continuing.');
    expect(onContinue).not.toHaveBeenCalled();
  });
  it('shows provider and model pickers and scopes models to the chosen provider', async () => {
    const anthropic = { ...provider, provider_id: 'claude-account', display_name: 'Anthropic', config: { preset: 'anthropic' },
      models: [defaultModelEntry('claude-sonnet-4-5')] };
    api.llmProviders.list.mockResolvedValue({ items: [provider, anthropic] });
    api.executor.list.mockResolvedValue([readyExecutor]);
    api.modelRouting.get.mockResolvedValue({ default: { model: 'openrouter-starter/openai/gpt-oss-120b' } });
    render(OnboardingAgent, { onBack: vi.fn() });
    await screen.findByLabelText('Agent name');
    expect(screen.getByLabelText('Provider')).toBeTruthy();
    expect(screen.getByLabelText('Model')).toBeTruthy();
    await fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'claude-account' } });
    expect((screen.getByLabelText('Model') as HTMLSelectElement).value).toBe('claude-account/claude-sonnet-4-5');
    expect(screen.queryByRole('option', { name: 'openai/gpt-oss-120b' })).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'Start conversation' }));
    await waitFor(() => expect(goto).toHaveBeenCalled());
    expect(api.agents.create.mock.calls[0][0].llm_config).toMatchObject({ provider_id: 'claude-account', model: 'claude-sonnet-4-5' });
    expect(api.modelRouting.update).not.toHaveBeenCalled();
  });
  it('retains a named system model until the user explicitly chooses a provider model', async () => {
    api.llmProviders.list.mockResolvedValue({ items: [provider] });
    api.executor.list.mockResolvedValue([readyExecutor]);
    api.modelRouting.get.mockResolvedValue({ default: { model: 'cognis/default' } });
    render(OnboardingAgent, { onBack: vi.fn() });
    await screen.findByLabelText('Agent name');
    expect((screen.getByLabelText('Model') as HTMLSelectElement).value).toBe('cognis/default');
    await fireEvent.click(screen.getByRole('button', { name: 'Start conversation' }));
    await waitFor(() => expect(goto).toHaveBeenCalled());
    expect(api.agents.create.mock.calls[0][0].llm_config.model).toBe('cognis/default');
    expect(api.modelRouting.update).not.toHaveBeenCalled();
  });
  it('keeps routing and model controls hidden and connects with one key action', async () => {
    const onContinue = vi.fn();
    render(OnboardingModels, { onChanged: vi.fn().mockResolvedValue(undefined), onContinue });
    await fireEvent.click(await screen.findByRole('button', { name: /OpenRouter Recommended/ }));
    await screen.findByLabelText('OpenRouter API key');
    expect(screen.queryByText('Provider for recommendations')).toBeNull();
    expect(screen.getByText('Advanced options').closest('details')?.open).toBe(false);
    await fireEvent.input(screen.getByLabelText('OpenRouter API key'), { target: { value: 'local-test-key' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Connect and continue' }));
    await waitFor(() => expect(onContinue).toHaveBeenCalledOnce());
    expect(api.llmProviders.test).toHaveBeenCalledWith(provider.provider_id);
    expect(api.modelRouting.update.mock.calls[0][0].companion_embedding.model).toContain('text-embedding-3-small');
  });
  it('does not advance on a rejected provider test and retries the saved provider', async () => {
    api.llmProviders.test.mockResolvedValueOnce({ ok: false, error_detail: 'Invalid key' });
    const onContinue = vi.fn();
    render(OnboardingModels, { onChanged: vi.fn().mockResolvedValue(undefined), onContinue });
    await fireEvent.click(await screen.findByRole('button', { name: /OpenRouter Recommended/ }));
    await screen.findByLabelText('OpenRouter API key');
    await fireEvent.input(screen.getByLabelText('OpenRouter API key'), { target: { value: 'local-test-key' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Connect and continue' }));
    await screen.findByRole('alert');
    expect(onContinue).not.toHaveBeenCalled();
    expect(api.modelRouting.update).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(onContinue).toHaveBeenCalledOnce());
    expect(api.llmProviders.create).toHaveBeenCalledOnce();
  });
  it('does not mutate executor state on mount, and continues only when connected', async () => {
    api.executor.list.mockResolvedValue([readyExecutor]);
    const onContinue = vi.fn();
    render(OnboardingExecutor, { onChanged: vi.fn().mockResolvedValue(undefined), onContinue });
    await screen.findByText('✓ My computer is connected.');
    expect(api.executor.create).not.toHaveBeenCalled();
    expect(api.executor.generateToken).not.toHaveBeenCalled();
    expect(screen.getByText('Advanced options').closest('details')?.open).toBe(false);
    await fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(onContinue).toHaveBeenCalledOnce());
  });
  it('creates and scopes an executor only after the explicit setup action', async () => {
    api.executor.create.mockResolvedValue({ ...readyExecutor, runtime_state: 'disconnected' });
    api.executor.generateToken.mockResolvedValue({ token: 'local-test-connection-code' });
    render(OnboardingExecutor, { onChanged: vi.fn(), onContinue: vi.fn() });
    await fireEvent.click(screen.getByRole('button', { name: 'Get setup command' }));
    await waitFor(() => expect(api.executor.generateToken).toHaveBeenCalledWith('my-computer'));
    expect(api.executor.create.mock.calls[0][0]).toMatchObject({ shared: false, enabled_tool_groups: ['filesystem', 'shell', 'browser'] });
  });
  it('retains the created agent if completion fails, then opens its owner chat on retry', async () => {
    api.llmProviders.list.mockResolvedValue({ items: [provider] });
    api.executor.list.mockResolvedValue([readyExecutor]);
    api.modelRouting.get.mockResolvedValue({ default: { model: 'openrouter-starter/openai/gpt-oss-120b' } });
    api.system.finishOnboarding.mockRejectedValueOnce(new Error('Companion unavailable'));
    render(OnboardingAgent, { onBack: vi.fn() });
    await screen.findByLabelText('Agent name');
    expect(screen.getByText('Advanced options').closest('details')?.open).toBe(false);
    await fireEvent.click(screen.getByRole('button', { name: 'Start conversation' }));
    await screen.findByText('Companion unavailable');
    expect(api.agents.create).toHaveBeenCalledOnce();
    const payload = api.agents.create.mock.calls[0][0];
    expect(payload.status).toBe('active');
    expect(payload.execution.executor_id).toBe('my-computer');
    expect(payload.tools.opt_in_builtin_tools).toEqual(INSTANCE_MANAGEMENT_TOOLS.map((tool) => tool.id));
    expect(payload.skills.items.map((skill: { skill_id: string }) => skill.skill_id)).toEqual(
      expect.arrayContaining(INSTANCE_MANAGEMENT_SKILLS)
    );
    await fireEvent.click(screen.getByRole('button', { name: 'Start conversation' }));
    await waitFor(() => expect(goto).toHaveBeenCalledWith('/chat/first-direct-chat'));
    expect(api.agents.create).toHaveBeenCalledOnce();
    expect(api.conversations.resolve).toHaveBeenCalledWith({ agent_id: payload.agent_id, context_type: 'web', scope: 'agent_direct' });
  });
  it('rechecks the executor before creating an agent', async () => {
    api.llmProviders.list.mockResolvedValue({ items: [provider] });
    api.executor.list.mockResolvedValueOnce([readyExecutor]).mockResolvedValue([]);
    api.modelRouting.get.mockResolvedValue({ default: { model: 'openrouter-starter/openai/gpt-oss-120b' } });
    render(OnboardingAgent, { onBack: vi.fn() });
    await screen.findByLabelText('Agent name');
    await fireEvent.click(screen.getByRole('button', { name: 'Start conversation' }));
    await screen.findByText(/Your computer disconnected/);
    expect(api.agents.create).not.toHaveBeenCalled();
  });
  it('keeps the explicitly chosen executor when two computers are connected', async () => {
    api.llmProviders.list.mockResolvedValue({ items: [provider] });
    api.executor.list.mockResolvedValue([readyExecutor, { ...readyExecutor, executor_id: 'second-computer' }]);
    api.modelRouting.get.mockResolvedValue({ default: { model: 'openrouter-starter/openai/gpt-oss-120b' } });
    render(OnboardingAgent, { selectedExecutorId: 'second-computer', onBack: vi.fn() });
    await screen.findByLabelText('Agent name');
    await fireEvent.click(screen.getByRole('button', { name: 'Start conversation' }));
    await waitFor(() => expect(goto).toHaveBeenCalled());
    expect(api.agents.create.mock.calls[0][0].execution.executor_id).toBe('second-computer');
  });
  it('does not adopt an unrelated existing primary agent', async () => {
    api.llmProviders.list.mockResolvedValue({ items: [provider] });
    api.executor.list.mockResolvedValue([readyExecutor]);
    api.agents.listAll.mockResolvedValue([{ agent_id: 'another-agent', status: 'active', agent_type: 'primary', owner_email: 'owner@cognis.localdev.me' }]);
    api.modelRouting.get.mockResolvedValue({ default: { model: 'openrouter-starter/openai/gpt-oss-120b' } });
    render(OnboardingAgent, { onBack: vi.fn() });
    await screen.findByLabelText('Agent name');
    expect(screen.queryByText(/is ready. Start a conversation/)).toBeNull();
  });
  it('recovers a committed creation whose response was lost, without a second POST', async () => {
    api.llmProviders.list.mockResolvedValue({ items: [provider] });
    api.executor.list.mockResolvedValue([readyExecutor]);
    api.modelRouting.get.mockResolvedValue({ default: { model: 'openrouter-starter/openai/gpt-oss-120b' } });
    api.agents.create.mockImplementationOnce(async (payload) => {
      api.agents.listAll.mockResolvedValue([{ ...payload, owner_email: 'owner@cognis.localdev.me' }]);
      throw new Error('Response lost after commit');
    });
    render(OnboardingAgent, { onBack: vi.fn() });
    await screen.findByLabelText('Agent name');
    await fireEvent.click(screen.getByRole('button', { name: 'Start conversation' }));
    await waitFor(() => expect(goto).toHaveBeenCalled());
    expect(api.agents.create).toHaveBeenCalledOnce();
  });
  it('does not complete setup if owner conversation resolution fails', async () => {
    api.llmProviders.list.mockResolvedValue({ items: [provider] });
    api.executor.list.mockResolvedValue([readyExecutor]);
    api.modelRouting.get.mockResolvedValue({ default: { model: 'openrouter-starter/openai/gpt-oss-120b' } });
    api.conversations.resolve.mockRejectedValueOnce(new Error('Chat unavailable'));
    render(OnboardingAgent, { onBack: vi.fn() });
    await screen.findByLabelText('Agent name');
    await fireEvent.click(screen.getByRole('button', { name: 'Start conversation' }));
    await screen.findByText('Chat unavailable');
    expect(api.system.finishOnboarding).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole('button', { name: 'Start conversation' }));
    await waitFor(() => expect(goto).toHaveBeenCalled());
    expect(api.agents.create).toHaveBeenCalledOnce();
  });
  it('validates the exact recovered draft rather than any owner primary', async () => {
    saveSetupDraft('owner@cognis.localdev.me', { agentId: 'saved-agent', executorId: 'my-computer' });
    api.llmProviders.list.mockResolvedValue({ items: [provider] });
    api.executor.list.mockResolvedValue([readyExecutor]);
    api.agents.listAll.mockResolvedValue([{
      agent_id: 'saved-agent', name: 'Saved assistant', status: 'active', agent_type: 'primary',
      owner_email: 'owner@cognis.localdev.me', execution: { executor_id: 'my-computer' },
      llm_config: { provider_id: 'disabled-provider', model: 'not-available' }
    }]);
    render(OnboardingAgent, { onBack: vi.fn() });
    await screen.findByRole('button', { name: 'Start conversation' });
    await fireEvent.click(screen.getByRole('button', { name: 'Start conversation' }));
    await screen.findByText(/Your agent’s model is no longer available/);
    expect(api.system.finishOnboarding).not.toHaveBeenCalled();
  });
});
