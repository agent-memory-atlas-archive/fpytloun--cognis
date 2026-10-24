import { describe, expect, it } from 'vitest';
import { initialSetupStep, starterRouting } from './onboarding-setup';
import { defaultModelEntry, type LLMProvider, type ModelRouting } from '$lib/types/api';

const provider = {
  provider_id: 'openrouter-starter',
  models: [
    defaultModelEntry('openai/gpt-oss-20b'), defaultModelEntry('openai/gpt-oss-120b'),
    { ...defaultModelEntry('openai/text-embedding-3-small'), supports_embedding: true },
    { ...defaultModelEntry('google/gemini-3.1-flash-image'), supports_image_generation: true }
  ]
} as LLMProvider;

describe('simple setup defaults', () => {
  it('configures all required roles and optional images in one operation', () => {
    const routes = starterRouting(provider, {} as ModelRouting, true);
    expect(routes.default.model).toBe('openrouter-starter/openai/gpt-oss-120b');
    expect(routes.companion_embedding?.model).toBe('openrouter-starter/openai/text-embedding-3-small');
    expect(routes.image_generation.model).toBe('openrouter-starter/google/gemini-3.1-flash-image');
    expect(routes.mnemory_extraction?.model).toBe(routes.companion_smart?.model);
  });
  it('never replaces existing embedding routes or other choices', () => {
    const current = { companion_embedding: { model: 'embedding-service/pinned-store-model', reasoning_effort: null } } as ModelRouting;
    const routes = starterRouting(provider, current, false);
    expect(routes.companion_embedding).toBe(current.companion_embedding);
    expect(routes.image_generation).toBeUndefined();
    expect(current).not.toHaveProperty('default');
  });
  it('fails clearly when required capabilities cannot be configured', () => {
    expect(() => starterRouting({ ...provider, models: [] }, {} as ModelRouting, true)).toThrow('Advanced options');
  });
  it('resumes at the first unfinished required step', () => {
    expect(initialSetupStep({})).toBe(0);
    expect(initialSetupStep({ agent_model_configured: true, companion_routes_configured: true })).toBe(1);
    expect(initialSetupStep({ agent_model_configured: true, companion_routes_configured: true, executor_tools_configured: true })).toBe(2);
  });
});
