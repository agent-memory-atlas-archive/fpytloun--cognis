import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import type { LLMProvider, ModelRouting } from '$lib/types/api';
import CompanionRouting from './CompanionRouting.svelte';

function provider(id: string, owner: string, status = 'active'): LLMProvider {
  return {
    provider_id: id, display_name: id, owner_email: owner, status,
    models: [
      { model_id: 'chat-model', supports_embedding: false, reasoning_efforts: ['none', 'low', 'medium', 'high'] },
      { model_id: 'vector-model', supports_embedding: true }
    ]
  } as LLMProvider;
}

describe('CompanionRouting', () => {
  it('offers global models with qualified IDs and separates embedding capability', async () => {
    render(CompanionRouting, {
      routing: {} as ModelRouting,
      providers: [
        provider('shared', 'system@cognis.local'),
        provider('private', 'admin@cognis.local'),
        provider('disabled', 'system@cognis.local', 'disabled')
      ]
    });
    const lite = screen.getByRole('combobox', { name: /Lite model(?! thinking)/ });
    const embedding = screen.getByRole('combobox', { name: /Embedding model/ });
    expect(within(lite).getAllByRole('option').map((item) => item.getAttribute('value')))
      .toEqual(['', 'shared/chat-model']);
    expect(within(embedding).getAllByRole('option').map((item) => item.getAttribute('value')))
      .toEqual(['', 'shared/vector-model']);
    await fireEvent.change(lite, { target: { value: 'shared/chat-model' } });
    expect((lite as HTMLSelectElement).value).toBe('shared/chat-model');
    expect(screen.getByText('Advanced task overrides')).toBeTruthy();
  });

  it('explains missing global providers rather than suggesting private credentials', () => {
    render(CompanionRouting, {
      routing: {} as ModelRouting,
      providers: [provider('private', 'admin@cognis.local')]
    });
    expect(screen.getByText(/Add a global provider/)).toBeTruthy();
  });

  it('preserves effort when changing a model and supports effort-only task overrides', async () => {
    render(CompanionRouting, {
      routing: {
        companion_lite: { model: 'shared/chat-model', reasoning_effort: 'low' },
        intaris_evaluation: { model: null, reasoning_effort: 'medium' }
      } as ModelRouting,
      providers: [provider('shared', 'system@cognis.local'), provider('other', 'system@cognis.local')]
    });
    const model = screen.getByRole('combobox', { name: /Lite model(?! thinking)/ });
    const effort = screen.getByRole('combobox', { name: 'Lite model thinking effort' });
    expect((effort as HTMLSelectElement).value).toBe('low');
    await fireEvent.change(model, { target: { value: 'other/chat-model' } });
    expect((effort as HTMLSelectElement).value).toBe('low');
    await fireEvent.click(screen.getByText('Advanced task overrides'));
    const taskModel = screen.getByRole('combobox', { name: 'Intaris safety evaluation' });
    const taskEffort = screen.getByRole('combobox', { name: 'Intaris safety evaluation thinking effort' });
    expect((taskModel as HTMLSelectElement).value).toBe('');
    expect((taskEffort as HTMLSelectElement).value).toBe('medium');
    await fireEvent.change(taskEffort, { target: { value: 'default' } });
    expect((taskEffort as HTMLSelectElement).value).toBe('default');
    expect((taskModel as HTMLSelectElement).value).toBe('');
    expect(screen.queryByRole('combobox', { name: 'Embedding model thinking effort' })).toBeNull();
  });
});
