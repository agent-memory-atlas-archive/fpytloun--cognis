import type { ContextUsage, GenerationPerformanceSnapshot, RuntimeSelection } from '$lib/types/api';
import type { SessionInfoData } from '$lib/sessionInfoCache';

/** A future selection must not be shown beside the previous model's effort. */
export function runtimeModelPresentation(
  usage: ContextUsage | null,
  selection: RuntimeSelection | null,
): { model: string | null; providerId: string | null; effort: string | null; selected: boolean } {
  const pending = selection != null && (
    !usage || selection.revision > (usage.runtime_selection_revision ?? -1)
  );
  return pending ? {
    model: selection.model ?? null,
    providerId: selection.provider_id ?? null,
    effort: selection.reasoning_effort ?? null,
    selected: true,
  } : {
    model: usage?.model ?? null,
    providerId: usage?.provider_id ?? null,
    effort: usage?.reasoning_effort ?? null,
    selected: false,
  };
}

export interface SessionDiagnostics {
  ownerSessionId: string | null;
  contextUsage: ContextUsage | null;
  lastGeneration: GenerationPerformanceSnapshot | null;
}

export function mergeContextUsage(
  current: ContextUsage | null,
  incoming: ContextUsage | null,
): ContextUsage | null {
  if (!incoming) return current;
  if (!current) return incoming;
  const currentRevision = current.runtime_metadata_revision;
  const incomingRevision = incoming.runtime_metadata_revision;
  if (
    currentRevision !== undefined
    && (incomingRevision === undefined || incomingRevision < currentRevision)
  ) {
    return current;
  }
  return incoming;
}

export function diagnosticsForSession(
  sessionId: string | null,
  info: SessionInfoData | null,
): SessionDiagnostics {
  if (!sessionId || info?.intaris_session_id !== sessionId) {
    return { ownerSessionId: sessionId, contextUsage: null, lastGeneration: null };
  }
  return {
    ownerSessionId: sessionId,
    contextUsage: info.context_usage ?? null,
    lastGeneration: info.last_generation ?? null,
  };
}

export function acceptsSessionDiagnostics(
  focusedSessionId: string | null,
  activeSessionId: string | null,
  sourceSessionId: string | null,
): boolean {
  return sourceSessionId !== null && sourceSessionId === (focusedSessionId ?? activeSessionId);
}
