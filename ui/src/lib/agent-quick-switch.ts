import type { Agent, AgentRuntimeProfile, RuntimeSelection } from '$lib/types/api';

export function quickProfileOverrides(selection?: RuntimeSelection | null): string[] {
  if (!selection) return [];
  const overrides: string[] = [];
  if (selection.model_source === 'session_override') overrides.push(`Model: ${selection.model ?? 'custom'}`);
  if (selection.reasoning_effort_source === 'session_override') overrides.push(`Thinking: ${selection.reasoning_effort ?? 'off'}`);
  if (selection.fast_mode_source === 'session_override') overrides.push(`Fast mode: ${selection.fast_mode ? 'on' : 'off'}`);
  return overrides;
}

export type RuntimeBySession = Readonly<Record<string, RuntimeSelection>>;
export const QUICK_PROFILE_RUNTIME_MAX_FAILURES = 2;

/** Record a session's runtime selection, keeping the newest revision. Returns
 * the same map when nothing changes so reactive callers can skip updates. */
export function recordRuntimeForSession(
  map: RuntimeBySession,
  sessionId: string,
  selection: RuntimeSelection
): RuntimeBySession {
  const current = map[sessionId];
  if (current && current.revision > selection.revision) return map;
  if (current === selection) return map;
  return { ...map, [sessionId]: selection };
}

/** Load a session's runtime once it is unknown, not already loading, and
 * under the bounded failure budget. Known selections never reload, so
 * returning to a visited session reuses its stored state. */
export function shouldLoadRuntimeForSession(
  map: RuntimeBySession,
  sessionId: string,
  inFlight: ReadonlySet<string>,
  failures: ReadonlyMap<string, number>
): boolean {
  return !map[sessionId]
    && !inFlight.has(sessionId)
    && (failures.get(sessionId) ?? 0) < QUICK_PROFILE_RUNTIME_MAX_FAILURES;
}

export const quickProfileColors = {
  neutral: 'rgb(var(--color-secondary))', blue: 'rgb(var(--color-blue-tone))', teal: 'rgb(var(--color-teal-tone))',
  amber: 'rgb(var(--color-orange-tone))', violet: 'rgb(var(--color-violet-tone))', rose: 'rgb(var(--color-pink-tone))'
} as const;

export interface QuickProfileOption {
  id: string;
  label: string;
  description: string;
  isDefault: boolean;
  color: NonNullable<AgentRuntimeProfile['quick_switch_color']>;
}

export interface QuickProfileSelection {
  options: QuickProfileOption[];
  toggle: boolean;
  defaultId: string;
}

export function agentQuickProfileSelection(
  agent: Pick<Agent, 'agent_profiles' | 'default_agent_profile_id'>
): QuickProfileSelection {
  const defaultId = agent.default_agent_profile_id || 'default';
  const quick = Object.entries(agent.agent_profiles ?? {})
    .filter(([, profile]) => profile.enabled !== false && profile.quick_switch === true)
    .sort(([leftId, left], [rightId, right]) =>
      (left.quick_switch_index ?? 0) - (right.quick_switch_index ?? 0)
      || leftId.localeCompare(rightId)
    );
  if (!quick.length) return { options: [], toggle: false, defaultId };
  const options = quick.map(([id, profile]) => ({
    id,
    label: id,
    description: profile.description ?? '',
    isDefault: id === defaultId,
    color: profile.quick_switch_color ?? 'neutral'
  }));
  if (!options.some((option) => option.isDefault)) {
    options.unshift({
      id: defaultId,
      label: defaultId === 'default' ? 'Default' : defaultId,
      description: agent.agent_profiles?.[defaultId]?.description ?? 'Agent default profile',
      isDefault: true,
      color: agent.agent_profiles?.[defaultId]?.quick_switch_color ?? 'neutral'
    });
  }
  return {
    options: options.length > 1 ? options : [],
    toggle: options.length === 2,
    defaultId
  };
}
