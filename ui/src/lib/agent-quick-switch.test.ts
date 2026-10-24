import { describe, expect, it } from 'vitest';
import { agentQuickProfileSelection } from './agent-quick-switch';
import type { AgentRuntimeProfile } from './types/api';

function profile(id: string, index = 0, enabled = true): AgentRuntimeProfile {
  return { profile_id: id, quick_switch: true, quick_switch_index: index, enabled };
}

describe('agentQuickProfileSelection', () => {
  it('hides unconfigured, disabled, and default-only selections', () => {
    expect(agentQuickProfileSelection({}).options).toEqual([]);
    expect(agentQuickProfileSelection({ agent_profiles: { smart: profile('smart', 0, false) } }).options).toEqual([]);
    expect(agentQuickProfileSelection({
      agent_profiles: { smart: profile('smart') }, default_agent_profile_id: 'smart'
    }).options).toEqual([]);
  });

  it('creates a default/smart toggle independently of agent-switch permission', () => {
    const selection = agentQuickProfileSelection({ agent_profiles: { smart: profile('smart') } });
    expect(selection.toggle).toBe(true);
    expect(selection.options.map((item) => item.id)).toEqual(['default', 'smart']);
  });

  it('prepends the configured default and sorts quick levels by index', () => {
    const selection = agentQuickProfileSelection({
      default_agent_profile_id: 'developer',
      agent_profiles: {
        critical: profile('critical', 3),
        worker: profile('worker', 1),
        architect: profile('architect', 2),
        developer: { profile_id: 'developer' }
      }
    });
    expect(selection.toggle).toBe(false);
    expect(selection.options.map((item) => item.id)).toEqual(['developer', 'worker', 'architect', 'critical']);
    expect(selection.options[0].isDefault).toBe(true);
  });

  it('retains the configured position of a quick default without duplicating it', () => {
    const selection = agentQuickProfileSelection({
      default_agent_profile_id: 'architect',
      agent_profiles: { critical: profile('critical', 2), architect: profile('architect', 1), worker: profile('worker') }
    });
    expect(selection.options.map((item) => item.id)).toEqual(['worker', 'architect', 'critical']);
    expect(selection.options.filter((item) => item.isDefault).map((item) => item.id)).toEqual(['architect']);
  });

  it('breaks index ties by profile ID', () => {
    expect(agentQuickProfileSelection({
      agent_profiles: { worker: profile('worker'), architect: profile('architect') }
    }).options.map((item) => item.id)).toEqual(['default', 'architect', 'worker']);
  });

  it.each([0, 2])('toggles when the quick default has index %s', (index) => {
    const selection = agentQuickProfileSelection({
      default_agent_profile_id: 'developer',
      agent_profiles: { developer: profile('developer', index), smart: profile('smart', 1) }
    });
    expect(selection.toggle).toBe(true);
    expect(selection.options).toHaveLength(2);
  });
});
