import type {
  ContextUsage,
  GenerationPerformanceSnapshot,
  IntarisSessionDetail,
  TokenUsage,
  RuntimeSelection
} from '$lib/types/api';
import { mergeContextUsage } from '$lib/sessionDiagnostics';
import { mergeLatestPerformance } from '$lib/generation-performance';

const MAX_ENTRIES = 16;
const MAX_PER_CONVERSATION = 8;
const TTL_MS = 120_000;
const HARD_EVICTION_MS = 300_000;

export interface SessionInfoData {
  intaris_session_id: string;
  intention: string | null;
  summary: string | null;
  status: string;
  maximum_outcome?: 'deny' | 'escalate' | 'approve' | null;
  total_calls: number;
  approved_count: number;
  denied_count: number;
  escalated_count: number;
  context_usage?: ContextUsage | null;
  last_generation?: GenerationPerformanceSnapshot | null;
  runtime_selection?: RuntimeSelection | null;
  inference_target?: IntarisSessionDetail['inference_target'];
  token_usage?: TokenUsage | null;
}

export function mergeRuntimeSelection(
  current: SessionInfoData,
  incoming: RuntimeSelection
): SessionInfoData {
  const selected = newestRuntimeSelection(current.runtime_selection, incoming);
  if (selected === current.runtime_selection) {
    return current;
  }
  return { ...current, runtime_selection: selected };
}

export function newestRuntimeSelection(
  current: RuntimeSelection | null | undefined,
  incoming: RuntimeSelection
): RuntimeSelection {
  return current && current.revision > incoming.revision ? current : incoming;
}

export function sessionInfoFromDetail(detail: IntarisSessionDetail): SessionInfoData {
  return { ...detail };
}

export function mergeSessionContextUsage(
  current: SessionInfoData,
  incoming: ContextUsage | null,
): SessionInfoData {
  const context = mergeContextUsage(current.context_usage ?? null, incoming);
  const target = current.inference_target;
  const targetIsStale = incoming && context === incoming && target && (
    (incoming.provider_id && incoming.provider_id !== target.provider_id)
    || (incoming.model && incoming.model !== target.model)
  );
  return { ...current, context_usage: context, inference_target: targetIsStale ? null : target };
}

/** Selection revisions and measured runtime revisions are separate clocks. */
export function mergeSessionInfo(
  current: SessionInfoData | null,
  incoming: SessionInfoData,
): SessionInfoData {
  if (!current || current.intaris_session_id !== incoming.intaris_session_id) return incoming;
  const context = mergeContextUsage(current.context_usage ?? null, incoming.context_usage ?? null);
  const incomingIsOlder = context === current.context_usage && context !== incoming.context_usage;
  return {
    ...current,
    ...incoming,
    context_usage: context,
    last_generation: mergeLatestPerformance(current.last_generation ?? null, incoming.last_generation ?? null),
    runtime_selection: incoming.runtime_selection
      ? newestRuntimeSelection(current.runtime_selection, incoming.runtime_selection)
      : current.runtime_selection,
    inference_target: incomingIsOlder
      ? current.inference_target
      : incoming.inference_target ?? current.inference_target,
  };
}

type Entry = {
  conversationId: string;
  value: SessionInfoData;
  storedAt: number;
};

const entries = new Map<string, Entry>();

function key(conversationId: string, sessionId: string): string {
  return `${conversationId}:${sessionId}`;
}

function prune(now = Date.now()): void {
  for (const [entryKey, entry] of entries) {
    if (now - entry.storedAt >= HARD_EVICTION_MS) entries.delete(entryKey);
  }
}

export function getSessionInfo(conversationId: string, sessionId: string): SessionInfoData | null {
  const now = Date.now();
  prune(now);
  const entryKey = key(conversationId, sessionId);
  const entry = entries.get(entryKey);
  if (!entry || now - entry.storedAt >= TTL_MS) return null;
  entries.delete(entryKey);
  entries.set(entryKey, entry);
  return { ...entry.value };
}

export function setSessionInfo(conversationId: string, sessionId: string, value: SessionInfoData): void {
  const entryKey = key(conversationId, sessionId);
  entries.delete(entryKey);
  entries.set(entryKey, { conversationId, value: { ...value }, storedAt: Date.now() });
  const matching = [...entries].filter(([, entry]) => entry.conversationId === conversationId);
  while (matching.length > MAX_PER_CONVERSATION) {
    const oldest = matching.shift();
    if (oldest) entries.delete(oldest[0]);
  }
  while (entries.size > MAX_ENTRIES) {
    const oldest = entries.keys().next().value;
    if (typeof oldest !== 'string') break;
    entries.delete(oldest);
  }
}

export function clearSessionInfoCache(conversationId?: string): void {
  if (!conversationId) {
    entries.clear();
    return;
  }
  for (const [entryKey, entry] of entries) {
    if (entry.conversationId === conversationId) entries.delete(entryKey);
  }
}
