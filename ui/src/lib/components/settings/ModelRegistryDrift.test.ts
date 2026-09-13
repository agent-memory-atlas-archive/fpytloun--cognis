import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, expect, it, vi } from 'vitest';
import ModelRegistryDrift from './ModelRegistryDrift.svelte';
import { defaultModelEntry } from '$lib/types/api';

afterEach(cleanup);

it('shows configured and registry values and emits only draft resets', async () => {
  const model = defaultModelEntry('claude-opus-5');
  const registry = { ...model, context_window: 1000000 };
  const onreset = vi.fn();
  render(ModelRegistryDrift, { model, registry, onreset });
  await fireEvent.click(screen.getByText('Registry drift: 1 differing field'));
  expect(screen.getByText('Configured: 128000')).toBeInTheDocument();
  expect(screen.getByText('Registry: 1000000')).toBeInTheDocument();
  await fireEvent.click(screen.getByRole('button', { name: 'Reset context_window' }));
  expect(onreset.mock.calls[0][0].context_window).toBe(1000000);
  expect(model.context_window).toBe(128000);
});

it('does not offer deletion or resets for absent models', () => {
  render(ModelRegistryDrift, { model: defaultModelEntry('claude-opus-5'), registry: null, onreset: vi.fn() });
  expect(screen.getByText(/Not returned by this discovery snapshot/)).toBeInTheDocument();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});
