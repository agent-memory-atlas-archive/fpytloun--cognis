import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, expect, it, vi } from 'vitest';
import { defaultModelEntry } from '$lib/types/api';
import ModelCard from './ModelCard.svelte';
import ModelRegistryDrift from './ModelRegistryDrift.svelte';

afterEach(cleanup);

it('shows unknown metadata rather than invented limits or tool support', () => {
  const model = { ...defaultModelEntry('private-chat'),
    provider_metadata: { catalog_provider: 'groq', catalog_status: 'lookup_failed', field_sources: {} } };
  render(ModelCard, { model, isDefault: false, onedit: vi.fn(), onremove: vi.fn() });
  expect(screen.getByText('Context unknown · Output limit unknown · Price unknown')).toBeInTheDocument();
  expect(screen.queryByText('tools')).not.toBeInTheDocument();
  expect(screen.getByText('Catalog: groq (lookup_failed)')).toBeInTheDocument();
});

it('reports an ID-only registry as partial, not aligned', () => {
  const model = defaultModelEntry('private-chat');
  render(ModelRegistryDrift, { model, registry: { model_id: model.model_id } as typeof model, onreset: vi.fn() });
  expect(screen.getByText('Partial metadata; no differences in supplied registry fields.')).toBeInTheDocument();
});
