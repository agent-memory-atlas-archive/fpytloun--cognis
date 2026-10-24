import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, waitFor, within } from '@testing-library/svelte';
import HookDetailSheet from './HookDetailSheet.svelte';
import { emptyHook, type AgentHook } from '$lib/hooks';

const mocks = vi.hoisted(() => ({
  create: vi.fn(), update: vi.fn(), remove: vi.fn()
}));
vi.mock('$app/navigation', () => ({ beforeNavigate: vi.fn() }));
vi.mock('$lib/api/client', () => ({
  api: { hooks: mocks }, asApiError: (error: Error) => error
}));
vi.mock('$lib/stores/toasts', () => ({ addToast: vi.fn() }));
const bundled: AgentHook = {
  ...emptyHook(), hook_id: 'system:self-improvement', revision: 1, bundled: true,
  name: 'Learn reusable skills', description: 'Create or update reusable skills.',
  trigger: 'conversation_idle', mode: 'fork', idle_seconds: 1800, prompt: 'Only verified lessons.'
};
const custom: AgentHook = { ...bundled, hook_id: 'hook-learning', bundled: false, revision: 7 };
const callbacks = () => ({ onClose: vi.fn(), onSaved: vi.fn(), onDeleted: vi.fn() });

describe('Hook detail sheet', () => {
  beforeEach(() => { vi.resetAllMocks(); });

  it('renders bundled behavior as readable details, not disabled inputs', async () => {
    const view = render(HookDetailSheet, { hook: bundled, ...callbacks() });
    await view.findByText('Only verified lessons.');
    expect(view.getByText('After 30 min idle')).toBeTruthy();
    expect(view.queryByRole('textbox')).toBeNull();
    expect(view.queryByRole('button', { name: 'Save hook' })).toBeNull();
    expect(view.queryByRole('button', { name: 'Delete hook' })).toBeNull();
  });

  it('customizes a copy without mutating the bundled source', async () => {
    const events = callbacks();
    mocks.create.mockImplementation(async definition => ({ ...definition, hook_id: 'new-hook', revision: 1, bundled: false }));
    const view = render(HookDetailSheet, { hook: bundled, ...events });
    await fireEvent.click(await view.findByRole('button', { name: 'Customize' }));
    await fireEvent.input(view.getByLabelText('Name', { exact: true }), { target: { value: 'My learner' } });
    await fireEvent.input(view.getByLabelText('Idle time (minutes)', { exact: true }), { target: { value: '60' } });
    await fireEvent.submit(view.container.querySelector('form') ?? document.querySelector('#hook-editor-form')!);
    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({ name: 'My learner', idle_seconds: 3600 })));
    expect(bundled.name).toBe('Learn reusable skills');
    expect(bundled.idle_seconds).toBe(1800);
    expect(mocks.update).not.toHaveBeenCalled();
    await waitFor(() => expect(events.onSaved).toHaveBeenCalled());
  });

  it('keeps user input and expected revision after a rejected update', async () => {
    mocks.update.mockRejectedValue(new Error('Revision conflict'));
    const view = render(HookDetailSheet, { hook: custom, ...callbacks() });
    await fireEvent.click(await view.findByRole('button', { name: 'Edit hook' }));
    await fireEvent.input(view.getByLabelText('Instructions', { exact: true }), { target: { value: 'My unsaved instructions' } });
    await fireEvent.submit(document.querySelector('#hook-editor-form')!);
    await waitFor(() => expect(view.getByRole('alert').textContent).toContain('Revision conflict'));
    expect(mocks.update).toHaveBeenCalledWith(expect.objectContaining({ revision: 7 }), expect.objectContaining({ prompt: 'My unsaved instructions' }));
    expect((view.getByLabelText('Instructions', { exact: true }) as HTMLTextAreaElement).value).toBe('My unsaved instructions');
  });

  it('validates advanced JSON without losing the draft', async () => {
    const view = render(HookDetailSheet, { hook: custom, ...callbacks() });
    await fireEvent.click(await view.findByRole('button', { name: 'Edit hook' }));
    await fireEvent.input(view.getByLabelText('Default parameters (JSON)', { exact: true }), { target: { value: '[]' } });
    await fireEvent.submit(document.querySelector('#hook-editor-form')!);
    await waitFor(() => expect(view.getByRole('alert').textContent).toContain('Parameters must be a JSON object'));
    expect(mocks.update).not.toHaveBeenCalled();
  });

  it('honors cancel on dirty close and blocks viewer editing', async () => {
    const events = callbacks();
    const view = render(HookDetailSheet, { hook: custom, ...events });
    await fireEvent.click(await view.findByRole('button', { name: 'Edit hook' }));
    await fireEvent.input(view.getByLabelText('Name', { exact: true }), { target: { value: 'Changed' } });
    await fireEvent.click(view.getByRole('button', { name: 'Close hook details' }));
    const confirmation = await view.findByRole('dialog', { name: 'Discard unsaved changes?' });
    await fireEvent.click(within(confirmation).getByRole('button', { name: 'Cancel' }));
    expect(events.onClose).not.toHaveBeenCalled();
    view.unmount();
    const readonly = render(HookDetailSheet, { hook: custom, readonly: true, ...callbacks() });
    await readonly.findByText('Only verified lessons.');
    expect(readonly.queryByRole('button', { name: 'Edit hook' })).toBeNull();
    expect(readonly.queryByRole('button', { name: 'Delete hook' })).toBeNull();
    expect(readonly.queryByRole('button', { name: 'Duplicate' })).toBeNull();
  });
});
