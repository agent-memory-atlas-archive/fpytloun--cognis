import { describe, expect, it } from 'vitest';
import { deriveGettingStartedSteps, shouldOfferOnboarding } from '$lib/getting-started';
import type { SystemDiagnostics } from '$lib/types/api';

const diagnostics: SystemDiagnostics = {
  readiness: { mnemory_reachable: true, intaris_reachable: true, onboarding_pending: true },
  ui: {}, database: {}, config: {}, providers: [], agents: {}, key_fingerprint: null
};
describe('first-run checklist', () => {
  it('requires models, companion routes, and executor before agent creation', () => {
    const steps = deriveGettingStartedSteps(diagnostics);
    expect(steps[0].done).toBe(true);
    expect(steps.find((step) => step.id === 'routing')?.done).toBe(false);
    expect(steps.findIndex((step) => step.id === 'executor')).toBeLessThan(steps.findIndex((step) => step.id === 'agents'));
  });
  it('never resurfaces terminal server-side state after configuration degrades', () => {
    expect(shouldOfferOnboarding(diagnostics)).toBe(true);
    expect(shouldOfferOnboarding({ ...diagnostics, readiness: { onboarding_pending: false, chat_ready: false } })).toBe(false);
    expect(shouldOfferOnboarding({ ...diagnostics, readiness: { onboarding_pending: true, chat_ready: true } })).toBe(false);
  });
  it('does not offer setup before server state is known', () => {
    expect(shouldOfferOnboarding({ ...diagnostics, readiness: {} })).toBe(false);
  });
});
