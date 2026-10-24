import { describe, expect, it } from 'vitest';
import { agentModelCapabilities } from './agent-model-capabilities';
import type { LLMProvider } from './types/api';
import type { InferenceRoute } from './inference-routes';

const providers = [
  { provider_id: 'first', config: { default_model: 'claude' }, models: [
    { model_id: 'claude', reasoning_efforts: ['default', 'low', 'high', 'max'], supports_fast_mode: true }
  ] },
  { provider_id: 'backup', config: {}, models: [
    { model_id: 'claude', reasoning_efforts: ['default', 'low', 'high'], supports_fast_mode: false }
  ] }
] as LLMProvider[];
const routes: InferenceRoute[] = [{
  route_id: 'chat-route', revision: 1, reference: 'cognis/chat',
  config: { name: 'chat', targets: [
    { provider_id: 'first', model: 'claude', priority: 0 },
    { provider_id: 'backup', model: 'claude', priority: 1 }
  ] }
}];
describe('agent model capabilities', () => {
  it('uses all route targets, not just the preferred account', () => {
    expect(agentModelCapabilities(providers, routes, 'cognis', 'cognis/chat')).toEqual({
      reasoning_efforts: ['default', 'low', 'high'], supports_fast_mode: false
    });
  });
  it('resolves route references independently of inherited provider selection', () => {
    expect(agentModelCapabilities(providers, routes, 'first', 'cognis/chat'))
      .toEqual(agentModelCapabilities(providers, routes, '', 'cognis/chat'));
  });
  it('fails closed for undiscovered routes and missing target metadata', () => {
    expect(agentModelCapabilities(providers, [], 'cognis', 'cognis/chat')).toBeNull();
    expect(agentModelCapabilities(providers.slice(0, 1), routes, 'cognis', 'cognis/chat')).toBeNull();
  });
  it('preserves direct-provider and default-model lookup', () => {
    expect(agentModelCapabilities(providers, routes, 'first', '')).toBe(providers[0].models[0]);
  });
});
