import type { ContextUsage, GenerationPerformanceSnapshot, IntarisSessionDetail, RuntimeSelection, TokenUsage } from '$lib/types/api';

export interface SessionDetailsData {
  session_id?: string;
  intaris_session_id: string;
  intention: string | null;
  summary: string | null;
  status: string;
  total_calls: number;
  approved_count: number;
  denied_count: number;
  escalated_count: number;
  context_usage?: ContextUsage | null;
  token_usage?: TokenUsage | null;
  last_generation?: GenerationPerformanceSnapshot | null;
  runtime_selection?: RuntimeSelection | null;
  inference_target?: IntarisSessionDetail['inference_target'];
}

export interface SessionDetailsProps {
  detail: SessionDetailsData;
  sessionId?: string;
  yoloMode?: boolean;
  contextUsage?: ContextUsage | null;
  tokenUsage?: TokenUsage | null;
  performance?: GenerationPerformanceSnapshot | null;
  onOpenIntaris?: ((intarisSessionId: string) => void | Promise<void>) | undefined;
  canStar?: boolean;
  starred?: boolean;
  starBusy?: boolean;
  onToggleStar?: (() => void) | undefined;
  canArchive?: boolean;
  canDelete?: boolean;
  archived?: boolean;
  archiveBusy?: boolean;
  deleteBusy?: boolean;
  onArchive?: (() => void | Promise<void>) | undefined;
  onRestore?: (() => void | Promise<void>) | undefined;
  onDelete?: (() => void | Promise<void>) | undefined;
}
