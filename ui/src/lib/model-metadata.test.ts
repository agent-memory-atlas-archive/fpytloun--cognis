import { describe, expect, it } from 'vitest';
import { createProviderForm, formatModelMetadata, formatTokenCount, modelEntryFromMetadata, providerFormToPayload } from '$lib/providers';
import { defaultModelEntry, type ModelEntry } from '$lib/types/api';

describe('model metadata', () => {
  it('renders missing limits and prices honestly', () => {
    const model = { model_id: 'private-chat' } as ModelEntry;
    expect(formatTokenCount(undefined)).toBe('unknown');
    expect(formatTokenCount(null)).toBe('unknown');
    expect(formatModelMetadata(model)).toBe('Context unknown · Output limit unknown · Price unknown');
  });

  it('does not present runtime safety defaults as discovery', () => {
    const model = {
      ...defaultModelEntry('private-chat'),
      provider_metadata: { catalog_status: 'lookup_failed', field_sources: {} }
    };
    expect(formatModelMetadata(model)).toBe('Context unknown · Output limit unknown · Price unknown');
    const entry = modelEntryFromMetadata(model);
    const form = createProviderForm();
    form.models = [entry];
    const payload = providerFormToPayload(form);
    const saved = (payload.config as { models: Record<string, unknown>[] }).models[0];
    expect(saved).not.toHaveProperty('context_window');
    expect(saved).not.toHaveProperty('max_output_tokens');
    expect(saved).not.toHaveProperty('supports_tools');
    entry.context_window = 64000;
    const edited = providerFormToPayload(form);
    expect((edited.config as { models: Record<string, unknown>[] }).models[0].context_window).toBe(64000);
  });

  it('preserves explicit false and zero, cache rates, and catalog fields across save', () => {
    const model = {
      ...defaultModelEntry('openai/gpt-oss-20b'),
      model_id: 'openai/gpt-oss-20b',
      context_window: 131072,
      max_output_tokens: 32768,
      supports_tools: false,
      input_cost_per_mtok: 0,
      output_cost_per_mtok: 0.3,
      cache_read_cost_per_mtok: 0.0375,
      model_mode: 'chat',
      pricing: { input_cost_per_token: 0 },
      provider_metadata: {
        catalog_provider: 'groq', catalog_status: 'matched',
        field_sources: { context_window: 'catalog:groq', max_output_tokens: 'catalog:groq',
          supports_tools: 'provider', input_cost_per_mtok: 'provider', output_cost_per_mtok: 'catalog:groq',
          cache_read_cost_per_mtok: 'catalog:groq', model_mode: 'catalog:groq', pricing: 'provider' }
      }
    } as ModelEntry;
    expect(formatModelMetadata(model)).toContain('$0/$0.3 per Mtok');
    expect(formatModelMetadata(model)).toContain('$0.0375/Mtok cache read');
    const form = createProviderForm();
    form.models = [modelEntryFromMetadata(model)];
    const payload = providerFormToPayload(form);
    const saved = (payload.config as { models: Record<string, unknown>[] }).models[0];
    expect(saved.supports_tools).toBe(false);
    expect(saved.input_cost_per_mtok).toBe(0);
    expect(saved.cache_read_cost_per_mtok).toBe(0.0375);
    expect(saved.pricing).toEqual({ input_cost_per_token: 0 });
    expect(saved).not.toHaveProperty('_initialValues');
  });

  it('shows transcription mode and per-second prices without chat token limits', () => {
    const model = { ...defaultModelEntry('whisper-large-v3'), model_id: 'whisper-large-v3', model_mode: 'audio_transcription',
      pricing: { input_cost_per_second: 0.00003 } } as ModelEntry;
    expect(formatModelMetadata(model)).toBe('audio transcription · $0.00003/s input');
  });

  it('saves only adapter-supplied fields from manually enriched Ollama models', () => {
    const response = {
      ...defaultModelEntry('ollama/private-chat'),
      context_window: 8192, max_output_tokens: 4096,
      supports_tools: true, supports_pdf_input: false,
      provider_metadata: { provider: 'ollama', field_sources: {
        context_window: 'provider', supports_tools: 'provider'
      } }
    };
    const form = createProviderForm();
    form.models = [modelEntryFromMetadata(response)];
    const saved = (providerFormToPayload(form).config as { models: Record<string, unknown>[] }).models[0];
    expect(saved.context_window).toBe(8192);
    expect(saved.supports_tools).toBe(true);
    expect(saved).not.toHaveProperty('max_output_tokens');
    expect(saved).not.toHaveProperty('supports_pdf_input');
  });
});
