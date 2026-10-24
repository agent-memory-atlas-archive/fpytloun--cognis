import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '$lib/api/client';
import { confirmAction } from '$lib/stores/confirm';
import Settings from './+page.svelte';
import { DEFAULT_USER_PREFERENCES } from '$lib/user-preferences';
import { saveUserPreferences, userPreferences } from '$lib/stores/userPreferences';
import type { UserPreferences } from '$lib/types/api';

vi.mock('$lib/stores/userPreferences', async () => {
  const { writable, get } = await import('svelte/store');
  const { DEFAULT_USER_PREFERENCES } = await import('$lib/user-preferences');
  const state = writable(structuredClone(DEFAULT_USER_PREFERENCES));
  return {
    userPreferences: state,
    loadUserPreferences: vi.fn(async () => get(state)),
    saveUserPreferences: vi.fn(async (next: UserPreferences) => { state.set(next); return next; })
  };
});

const navigation = vi.hoisted(() => ({
  callback: undefined as undefined | ((event: { cancel: () => void }) => void),
  reset: undefined as undefined | (() => void)
}));
vi.mock('$app/navigation', () => ({
  beforeNavigate: (callback: typeof navigation.callback) => { navigation.callback = callback; },
  goto: vi.fn()
}));
vi.mock('$lib/stores/auth', async () => {
  const { writable } = await import('svelte/store');
  const state = writable({ user: { role: 'admin', email: 'owner@cognis.local', name: 'Owner' } });
  return { auth: {
    subscribe: state.subscribe,
    getSnapshot: vi.fn(() => ({ user: { role: 'admin', email: 'owner@cognis.local', name: 'Owner' } })),
    updateUser: vi.fn()
  } };
});
vi.mock('$lib/stores/tabReset', () => ({
  onTabReset: (_href: string, callback: () => void) => { navigation.reset = callback; return () => {}; }
}));
vi.mock('$lib/stores/confirm', () => ({ confirmAction: vi.fn().mockResolvedValue(true) }));
vi.mock('$lib/stores/toasts', () => ({ addToast: vi.fn() }));

function leavePage(): { prompted: boolean; cancelled: boolean } {
  const cancel = vi.fn();
  navigation.callback?.({ cancel });
  return { prompted: vi.mocked(window.confirm).mock.calls.length > 0, cancelled: cancel.mock.calls.length > 0 };
}

beforeEach(() => {
  vi.restoreAllMocks();
  (userPreferences as unknown as { set(value: UserPreferences): void }).set(structuredClone(DEFAULT_USER_PREFERENCES));
  vi.mocked(saveUserPreferences).mockClear();
  HTMLElement.prototype.scrollIntoView = vi.fn();
  vi.spyOn(window, 'confirm').mockReturnValue(false);
  window.history.replaceState({}, '', '/settings');
  vi.spyOn(api.llmProviders, 'list').mockResolvedValue({ items: [], has_more: false, cursor: null });
  vi.spyOn(api.secrets, 'list').mockResolvedValue([]);
  vi.spyOn(api.credentials, 'list').mockResolvedValue([]);
  vi.spyOn(api.executor, 'list').mockResolvedValue([]);
  vi.spyOn(api.localModels, 'deployments').mockResolvedValue([]);
  vi.spyOn(api.system, 'diagnostics').mockReturnValue(new Promise(() => {}));
  vi.spyOn(api.system, 'health').mockReturnValue(new Promise(() => {}));
  vi.spyOn(api.tools, 'listMcpServerConfigs').mockResolvedValue([]);
  vi.spyOn(api.tools, 'executorTools').mockResolvedValue([]);
  vi.spyOn(api.executor, 'status').mockResolvedValue({
    executor_type: 'websocket', status: 'healthy', active_executors: 0,
    capabilities: {}, native_tools: [], available_executor_types: ['websocket']
  });
  vi.spyOn(api.auth, 'listApiKeys').mockResolvedValue([]);
  vi.spyOn(api.users, 'list').mockResolvedValue({ items: [], cursor: null, has_more: false });
  vi.spyOn(api.settings, 'stepProfiles').mockResolvedValue([]);
  vi.spyOn(api.settings, 'list').mockResolvedValue([]);
});
afterEach(cleanup);

describe('Settings loading and unsaved changes', () => {
  it('saves independent Family and Appearance choices without replacing unrelated preferences', async () => {
    window.history.replaceState({}, '', '/settings?tab=display');
    render(Settings);
    const family = await screen.findByRole('combobox', { name: /^Family/ });
    const appearance = screen.getByRole('combobox', { name: /^Appearance/ });
    expect(family).toHaveValue('classic');
    expect(appearance).toHaveValue('system');
    expect([...family.querySelectorAll('option')].map((option) => option.textContent)).toEqual([
      'Porcelain', 'Classic', 'Gruvbox', 'Paper'
    ]);
    await fireEvent.change(family, { target: { value: 'paper' } });
    await waitFor(() => expect(family).not.toBeDisabled());
    expect(saveUserPreferences).toHaveBeenLastCalledWith({
      ...DEFAULT_USER_PREFERENCES,
      display: { ...DEFAULT_USER_PREFERENCES.display, theme_family: 'paper' }
    });
    await fireEvent.change(appearance, { target: { value: 'dark' } });
    await waitFor(() => expect(appearance).not.toBeDisabled());
    expect(saveUserPreferences).toHaveBeenLastCalledWith({
      ...DEFAULT_USER_PREFERENCES,
      display: { ...DEFAULT_USER_PREFERENCES.display, theme_family: 'paper', theme: 'dark' }
    });
    expect(family).toHaveValue('paper');
  });
  it('loads provider settings without diagnostics, other tabs or rollout targets', async () => {
    vi.mocked(api.localModels.deployments).mockReturnValue(new Promise(() => {}));
    render(Settings);
    await screen.findByRole('heading', { name: 'LLM providers' });
    await tick();
    expect(api.system.diagnostics).not.toHaveBeenCalled();
    expect(api.system.health).not.toHaveBeenCalled();
    expect(api.auth.listApiKeys).not.toHaveBeenCalled();
    expect(api.tools.listMcpServerConfigs).not.toHaveBeenCalled();
    expect(api.users.list).not.toHaveBeenCalled();
    expect(leavePage()).toEqual({ prompted: false, cancelled: false });
  });

  it('does not warn on leaving while data is pending or after a failed load', async () => {
    let reject!: (error: Error) => void;
    vi.mocked(api.llmProviders.list).mockReturnValue(new Promise((_resolve, rejectRequest) => { reject = rejectRequest; }));
    render(Settings);
    expect(leavePage().prompted).toBe(false);
    reject(new Error('Provider registry unavailable'));
    await screen.findByRole('button', { name: 'Retry settings' });
    expect(leavePage().prompted).toBe(false);
    expect(screen.queryByPlaceholderText('My OpenAI')).not.toBeInTheDocument();
  });

  it('warns on genuine provider edits, but not after reverting them', async () => {
    render(Settings);
    const name = await screen.findByPlaceholderText('My OpenAI');
    await tick();
    await fireEvent.input(name, { target: { value: 'Edited provider' } });
    expect(leavePage()).toEqual({ prompted: true, cancelled: true });
    vi.mocked(window.confirm).mockClear();
    await fireEvent.input(name, { target: { value: '' } });
    expect(leavePage()).toEqual({ prompted: false, cancelled: false });
  });

  it('loads account deep links without provider or executor registries and initializes a clean baseline', async () => {
    window.history.replaceState({}, '', '/settings?tab=account');
    render(Settings);
    await screen.findByText('Change password');
    await tick();
    expect(api.auth.listApiKeys).toHaveBeenCalledTimes(1);
    expect(api.llmProviders.list).not.toHaveBeenCalled();
    expect(api.executor.list).not.toHaveBeenCalled();
    expect(leavePage().prompted).toBe(false);
  });

  it('loads another tab on demand without counting mounted bindings as edits', async () => {
    render(Settings);
    await screen.findByRole('heading', { name: 'LLM providers' });
    await tick();
    await fireEvent.click(screen.getAllByRole('tab', { name: /^account$/ })[0]);
    await screen.findByText('Change password');
    await tick();
    expect(confirmAction).not.toHaveBeenCalled();
    expect(api.auth.listApiKeys).toHaveBeenCalledTimes(1);
    expect(leavePage().prompted).toBe(false);
  });

  it('reloads the default tab and clean baseline through the mobile Settings reset', async () => {
    window.history.replaceState({}, '', '/settings?tab=account');
    render(Settings);
    await screen.findByText('Change password');
    await tick();
    navigation.reset?.();
    await screen.findByRole('heading', { name: 'LLM providers' });
    await tick();
    expect(api.llmProviders.list).toHaveBeenCalledTimes(1);
    expect(leavePage().prompted).toBe(false);
  });

  it.each(['tools', 'executors'])('loads cross-panel tool dependencies on a fresh %s deep link', async (tab) => {
    window.history.replaceState({}, '', `/settings?tab=${tab}`);
    render(Settings);
    await waitFor(() => expect(api.tools.executorTools).toHaveBeenCalled());
    await waitFor(() => expect(api.tools.listMcpServerConfigs).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText('Loading settings')).not.toBeInTheDocument());
  });
});
