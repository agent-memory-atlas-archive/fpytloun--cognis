import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, expect, it, vi } from 'vitest';
import ModelEditModal from './ModelEditModal.svelte';
import { defaultModelEntry } from '$lib/types/api';
import { createProviderForm, providerFormToPayload } from '$lib/providers';

afterEach(cleanup);

it('retains an explicit capability disable even for a newly added model', async () => {
  const model = defaultModelEntry('claude-opus-5');
  const onsave = vi.fn();
  render(ModelEditModal, { model, onclose: vi.fn(), onsave });
  const toggle = screen.getByRole('checkbox', { name: 'Fast mode (account access not confirmed)' });
  await fireEvent.click(toggle);
  await fireEvent.click(toggle);
  await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  const form = createProviderForm();
  form.models = [onsave.mock.calls[0][0]];
  const payload = JSON.parse(JSON.stringify(providerFormToPayload(form)));
  expect(payload.config.models[0].supports_fast_mode).toBe(false);
});

it('resets a single field without rewriting independent context limits', async () => {
  const model = { ...defaultModelEntry('claude-opus-5'), max_context_window: 1000000 };
  const onsave = vi.fn();
  render(ModelEditModal, {
    model, registry: { ...model, supports_fast_mode: true }, registryChecked: true,
    onclose: vi.fn(), onsave,
  });
  await fireEvent.click(screen.getByText('Registry drift: 1 differing field'));
  await fireEvent.click(screen.getByRole('button', { name: 'Reset supports_fast_mode' }));
  await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  expect(onsave.mock.calls[0][0].supports_fast_mode).toBe(true);
  expect(onsave.mock.calls[0][0].max_context_window).toBe(1000000);
  expect(model.supports_fast_mode).toBe(false);
});
