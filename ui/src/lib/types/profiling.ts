/** Admin-only diagnostics API; aggregate reports never include application payloads. */
export interface ProfilingOptions {
  level?: 'light' | 'cpu' | 'allocations' | 'full';
  duration_seconds?: number;
  sample_interval_ms?: number;
  allocation_interval_seconds?: number;
  traceback_depth?: number;
  allocation_snapshots?: boolean;
}

export interface StartProfilingRequest {
  capture_id: string;
  options?: ProfilingOptions;
  targets?: string[] | null;
}

export interface ProfilingResponse {
  version: number;
  meta: Record<string, unknown>;
  desired: string;
  controllers: Record<string, Record<string, unknown>>;
  reports: Record<string, Record<string, unknown>>;
}

export interface ProfilingDiscoveryResponse {
  owner_id: string;
  allowed: boolean;
  ready_owners: string[];
  levels: string[];
  local: Record<string, unknown> | null;
  coordination_error: string | null;
}
