import { MAX_RETAINED_WORKSPACE_WINDOWS, type WorkspaceOpenResult } from './workspace';

/** These reasons travel in the existing native ok/key/reason envelope. */
export const workspaceCapacityReason = {
  retained: 'capacity-retained',
  agents: 'capacity-pinned-agents',
} as const;
export type WorkspaceCapacityReason = typeof workspaceCapacityReason[keyof typeof workspaceCapacityReason];
type WorkspaceOpenFailure = Exclude<WorkspaceOpenResult, { key: string }>;

export function workspaceOpenFailure(reason: string): WorkspaceOpenFailure {
  if (reason === workspaceCapacityReason.retained) {
    return { status: 'capped', limit: MAX_RETAINED_WORKSPACE_WINDOWS, scope: 'retained' };
  }
  if (reason === workspaceCapacityReason.agents) {
    return { status: 'capped', limit: MAX_RETAINED_WORKSPACE_WINDOWS, scope: 'pinned-agents' };
  }
  return { status: 'failed', reason };
}

export function workspaceOpenErrorReason(error: unknown): string {
  return error instanceof Error ? error.message : 'open-failed';
}

export function workspaceOpenFailureMessage(result: WorkspaceOpenFailure): string {
  if (result.status === 'failed') {
    return result.reason === 'uncertain'
      ? 'Window open outcome is uncertain. Wait for workspace synchronization before trying again.'
      : `Could not open workspace window (${result.reason}).`;
  }
  const scope = result.scope ?? (result.limit === MAX_RETAINED_WORKSPACE_WINDOWS ? 'retained' : 'visible');
  if (scope === 'pinned-agents') {
    return `Pinned agent limit reached (${result.limit}). Unpin an agent explicitly before pinning another.`;
  }
  if (scope === 'retained') {
    return `Retained window limit reached (${result.limit}), including minimized windows. Restore an existing window or close one before opening a new window.`;
  }
  return `Visible window limit reached (${result.limit}). Minimize or close a window before restoring or opening another.`;
}
