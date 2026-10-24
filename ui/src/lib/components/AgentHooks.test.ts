import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, waitFor } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import AgentHooks from './AgentHooks.svelte';
import { addToast } from '$lib/stores/toasts';

const mocks = vi.hoisted(() => ({
  list: vi.fn(), assignments: vi.fn(), assign: vi.fn(), unassign: vi.fn()
}));
vi.mock('$lib/api/client', () => ({
  api: { hooks: mocks }, asApiError: (error: Error) => error
}));
vi.mock('$lib/stores/auth', () => ({ auth: writable({ user: { role: 'user' } }) }));
vi.mock('$lib/stores/toasts', () => ({ addToast: vi.fn() }));

describe('AgentHooks', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.list.mockResolvedValue({ items: [
      { hook_id: 'system:recall-reminder', name: 'Recall relevant memories', bundled: true }
    ] });
    mocks.assignments.mockResolvedValue({ items: [] });
    mocks.assign.mockImplementation(async (_agent, assignment) => assignment);
    mocks.unassign.mockResolvedValue({ ok: true });
  });
  it('enables, disables, and removes an assignment through agent-scoped APIs', async () => {
    const view = render(AgentHooks, { agentId: 'hook-owner-agent' });
    await view.findByText('No hooks assigned. Choose a bundled hook or create your own.');
    await fireEvent.change(view.getByLabelText('Hook to assign'), {
      target: { value: 'system:recall-reminder' }
    });
    await fireEvent.click(view.getByRole('button', { name: 'Enable hook' }));
    await waitFor(() => expect(mocks.assign).toHaveBeenCalledWith('hook-owner-agent', {
      hook_id: 'system:recall-reminder', enabled: true, parameters: {}
    }));
    expect(addToast).toHaveBeenLastCalledWith('Hook enabled.', 'success');
    expect(view.queryByText(/Applies immediately/)).toBeNull();
    await fireEvent.click(await view.findByRole('checkbox', { name: 'Enabled' }));
    await waitFor(() => expect(mocks.assign).toHaveBeenLastCalledWith('hook-owner-agent', {
      hook_id: 'system:recall-reminder', enabled: false, parameters: {}
    }));
    expect(addToast).toHaveBeenLastCalledWith('Hook disabled.', 'success');
    await fireEvent.click(view.getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(mocks.unassign).toHaveBeenCalledWith(
      'hook-owner-agent', 'system:recall-reminder'
    ));
    expect(addToast).toHaveBeenLastCalledWith('Hook removed.', 'success');
  });
  it('reports failed assignment without claiming activation', async () => {
    mocks.assign.mockRejectedValue(new Error('Memory is disabled'));
    const view = render(AgentHooks, { agentId: 'hook-owner-agent' });
    await view.findByText('No hooks assigned. Choose a bundled hook or create your own.');
    await fireEvent.change(view.getByLabelText('Hook to assign'), {
      target: { value: 'system:recall-reminder' }
    });
    await fireEvent.click(view.getByRole('button', { name: 'Enable hook' }));
    await waitFor(() => expect(view.getByRole('alert').textContent).toContain('Memory is disabled'));
    expect(view.queryByRole('checkbox')).toBeNull();
    expect(addToast).not.toHaveBeenCalled();
  });
  it('notifies only after a toggle is saved and restores its state on failure', async () => {
    mocks.assignments.mockResolvedValue({ items: [{
      hook_id: 'system:recall-reminder', enabled: true, parameters: {}
    }] });
    let rejectSave!: (error: Error) => void;
    mocks.assign.mockImplementation(() => new Promise((_resolve, reject) => { rejectSave = reject; }));
    const view = render(AgentHooks, { agentId: 'hook-owner-agent' });
    const toggle = await view.findByRole('checkbox', { name: 'Enabled' });
    await fireEvent.click(toggle);
    expect(addToast).not.toHaveBeenCalled();
    expect(toggle).toBeChecked();
    expect(toggle).toBeDisabled();
    rejectSave(new Error('Unable to save hook'));
    await view.findByRole('alert');
    expect(toggle).toBeChecked();
    expect(toggle).toBeEnabled();
    expect(addToast).not.toHaveBeenCalled();
  });
  it('confirms parameter saves without claiming success for invalid JSON', async () => {
    mocks.assignments.mockResolvedValue({ items: [{
      hook_id: 'system:recall-reminder', enabled: true, parameters: {}
    }] });
    const view = render(AgentHooks, { agentId: 'hook-owner-agent' });
    await fireEvent.click(await view.findByRole('button', { name: 'Parameters' }));
    const input = view.getByRole('textbox', { name: 'Parameter overrides (JSON object)' });
    await fireEvent.input(input, { target: { value: '[]' } });
    await fireEvent.click(view.getByRole('button', { name: 'Save parameters' }));
    expect(addToast).not.toHaveBeenCalled();
    expect(mocks.assign).not.toHaveBeenCalled();
    await fireEvent.input(input, { target: { value: '{"limit":2}' } });
    await fireEvent.click(view.getByRole('button', { name: 'Save parameters' }));
    await waitFor(() => expect(addToast).toHaveBeenCalledWith('Hook parameters saved.', 'success'));
  });
  it('shows the learning write behavior before enabling the bundled preset', async () => {
    mocks.list.mockResolvedValue({ items: [{
      hook_id: 'system:self-improvement', name: 'Learn reusable skills', bundled: true,
      description: 'Creates or updates versioned Cognis skills after 15 idle minutes.'
    }] });
    const view = render(AgentHooks, { agentId: 'hook-owner-agent' });
    await view.findByText('No hooks assigned. Choose a bundled hook or create your own.');
    await fireEvent.change(view.getByLabelText('Hook to assign'), {
      target: { value: 'system:self-improvement' }
    });
    expect(view.getByText('Creates or updates versioned Cognis skills after 15 idle minutes.')).toBeTruthy();
    await fireEvent.click(view.getByRole('button', { name: 'Enable hook' }));
    await waitFor(() => expect(mocks.assign).toHaveBeenCalledWith('hook-owner-agent', {
      hook_id: 'system:self-improvement', enabled: true, parameters: {}
    }));
  });
});
