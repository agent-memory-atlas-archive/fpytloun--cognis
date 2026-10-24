import type { IntarisEvaluation, SessionPolicy } from '$lib/types/api';

export const DEFAULT_INTARIS_EVALUATION: IntarisEvaluation = 'balanced';

export function policyEvaluation(policy: SessionPolicy | Record<string, unknown> | null | undefined): IntarisEvaluation | '' {
  const value = policy?.intaris_evaluation;
  return value === 'legacy' || value === 'strict' || value === 'balanced' || value === 'bounded_autonomy'
    ? value : '';
}

export function emptySessionPolicy(): SessionPolicy {
  return { allow_policies: [], deny_policies: [] };
}

export function normalizeSessionPolicy(policy: SessionPolicy | Record<string, unknown> | null | undefined): SessionPolicy {
  const allow = Array.isArray(policy?.allow_policies) ? policy.allow_policies : [];
  const deny = Array.isArray(policy?.deny_policies) ? policy.deny_policies : [];
  return {
    allow_policies: allow.filter((item): item is string | Record<string, unknown> => typeof item === 'string' || isRecord(item)),
    deny_policies: deny.filter((item): item is string | Record<string, unknown> => typeof item === 'string' || isRecord(item)),
    ...(policyEvaluation(policy) ? { intaris_evaluation: policyEvaluation(policy) as IntarisEvaluation } : {})
  };
}

export function policyText(policy: SessionPolicy | Record<string, unknown> | null | undefined, key: 'allow_policies' | 'deny_policies'): string {
  return normalizeSessionPolicy(policy)[key]
    .map((item) => (typeof item === 'string' ? item : JSON.stringify(item)))
    .join('\n');
}

export function policyFromText(allowText: string, denyText: string, evaluation?: IntarisEvaluation | ''): SessionPolicy {
  return {
    allow_policies: parsePolicyLines(allowText),
    deny_policies: parsePolicyLines(denyText),
    ...(evaluation !== undefined ? { intaris_evaluation: evaluation || null } : {})
  };
}

export function hasSessionPolicy(policy: SessionPolicy | Record<string, unknown> | null | undefined): boolean {
  const normalized = normalizeSessionPolicy(policy);
  return !!normalized.intaris_evaluation || normalized.allow_policies.length > 0 || normalized.deny_policies.length > 0;
}

function parsePolicyLines(text: string): Array<string | Record<string, unknown>> {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      if (!line.startsWith('{')) return line;
      try {
        const parsed = JSON.parse(line) as unknown;
        return isRecord(parsed) ? parsed : line;
      } catch {
        return line;
      }
    });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
