import { describe, expect, it } from 'vitest';
import { modelDrift, resetModelDrift } from './model-drift';
import { createProviderForm, providerFormToPayload } from './providers';
import { defaultModelEntry, type ModelEntry } from './types/api';

describe('model registry drift', () => {
  const model = { ...defaultModelEntry('claude-opus-5'), context_window: 64000, supports_fast_mode: false };
  const registry = { model_id: model.model_id, context_window: 1000000, supports_fast_mode: true } as ModelEntry;

  it('compares only supplied fields, never equating partial discovery with removal', () => {
    expect(modelDrift(model, registry)).toEqual(['context_window', 'supports_fast_mode']);
    expect(modelDrift(model, null)).toEqual([]);
    expect(modelDrift(model, { model_id: 'claude-sonnet-5' } as ModelEntry)).toEqual([]);
  });

  it('resets one field or all compared fields without mutating inputs or losing unknown fields', () => {
    const one = resetModelDrift(model, registry, 'supports_fast_mode');
    expect(one.context_window).toBe(64000);
    expect(one.supports_fast_mode).toBe(true);
    const all = resetModelDrift(model, registry);
    expect(all.context_window).toBe(1000000);
    expect(all.max_output_tokens).toBe(model.max_output_tokens);
    expect(model.context_window).toBe(64000);
    expect(model.supports_fast_mode).toBe(false);
  });

  it('compares capability sets independent of ordering', () => {
    expect(modelDrift(
      { ...model, reasoning_efforts: ['default', 'high'] },
      { ...model, reasoning_efforts: ['high', 'default'] }
    )).toEqual([]);
  });

  it('preserves explicit false and does not pin unchanged inherited capabilities on save', () => {
    const form = createProviderForm({
      provider_id: 'anthropic', config: { preset: 'anthropic', models: [{ model_id: model.model_id }] },
      display_name: 'Anthropic', location: 'controller', backend: 'litellm',
      is_default: false, status: 'active', created_at: null, updated_at: null, last_test: null,
      models: [{ ...defaultModelEntry(model.model_id), supports_fast_mode: true }],
    });
    expect(form.models[0].supports_fast_mode).toBe(true);
    const initial = providerFormToPayload(form) as { config: { models: ModelEntry[] } };
    expect(initial.config.models[0].supports_fast_mode).toBeUndefined();
    form.models = [resetModelDrift(form.models[0], { model_id: model.model_id, supports_fast_mode: false } as ModelEntry)];
    const payload = JSON.parse(JSON.stringify(providerFormToPayload(form)));
    expect(payload.config.models[0].supports_fast_mode).toBe(false);
    expect(payload.config.models[0]._configuredFields).toBeUndefined();
    expect(payload.config.models[0]._initialValues).toBeUndefined();
  });
});
