import { describe, expect, it } from 'vitest';
import { hasSessionPolicy, normalizeSessionPolicy, policyEvaluation, policyFromText } from './session-policy';

describe('human Intaris evaluation selection', () => {
  it.each(['legacy', 'strict', 'balanced', 'bounded_autonomy'] as const)('round-trips %s with prose clauses', (mode) => {
    const policy = policyFromText('Read source', 'No push', mode);
    expect(policyEvaluation(normalizeSessionPolicy(policy))).toBe(mode);
    expect(policy.allow_policies).toEqual(['Read source']);
    expect(policy.deny_policies).toEqual(['No push']);
    expect(hasSessionPolicy(policy)).toBe(true);
  });
  it('clears overrides explicitly and distinguishes omission', () => {
    expect(policyFromText('', '', '').intaris_evaluation).toBeNull();
    expect(policyFromText('', '')).not.toHaveProperty('intaris_evaluation');
    expect(policyEvaluation({ intaris_evaluation: 'unknown' })).toBe('');
  });
});
