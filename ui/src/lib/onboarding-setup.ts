import { recommendedRoutes } from '$lib/onboarding';
import type { LLMProvider, ModelRouting } from '$lib/types/api';

/** Add only missing defaults. Existing routes and embedding-store identity stay intact. */
export function starterRouting(provider: LLMProvider, current: ModelRouting, images: boolean): ModelRouting {
  const additions = recommendedRoutes(provider, current);
  if (!images) delete additions.image_generation;
  const result = {
    ...current,
    ...Object.fromEntries(Object.entries(additions).map(([role, value]) => [role, { ...value, reasoning_effort: null }]))
  } as ModelRouting;
  for (const role of ['default', 'companion_lite', 'companion_smart', 'companion_embedding'] as const) {
    if (!result[role]?.model) {
      throw new Error('This provider is missing a recommended model. Use Advanced options to choose another provider or model.');
    }
  }
  return result;
}

export function initialSetupStep(readiness: Record<string, boolean>): number {
  if (!readiness.agent_model_configured || !readiness.companion_routes_configured) return 0;
  if (!readiness.executor_tools_configured) return 1;
  return 2;
}

export interface SetupDraft { executorId?: string; agentId?: string }
/** Non-secret draft identity, scoped to the signed-in owner for reload recovery. */
export function loadSetupDraft(owner: string): SetupDraft {
  try {
    const value = JSON.parse(localStorage.getItem(`cognis.setup.draft:${owner}`) || '{}');
    return {
      executorId: typeof value?.executorId === 'string' ? value.executorId : undefined,
      agentId: typeof value?.agentId === 'string' ? value.agentId : undefined
    };
  } catch { return {}; }
}
export function saveSetupDraft(owner: string, delta: SetupDraft): void {
  if (!owner) throw new Error('Sign in again before continuing setup.');
  localStorage.setItem(`cognis.setup.draft:${owner}`, JSON.stringify({ ...loadSetupDraft(owner), ...delta }));
}
