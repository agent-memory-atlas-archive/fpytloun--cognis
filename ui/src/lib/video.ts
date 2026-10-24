/** Native video jobs, not a local editing/timeline engine. */
export interface VideoPolicy {
  enabled: boolean;
  per_job_usd: string | number;
  daily_usd: string | number;
  max_active_jobs: number;
  max_output_bytes: number;
  model_max_cost_usd: Record<string, string | number>;
}

export interface VideoJob {
  job_id: string;
  version: number;
  status: string;
  operation: string;
  provider_id: string;
  model: string;
  estimated_cost_usd: string | null;
  actual_cost_usd: string | null;
  cost_status: string;
  cancel_requested: boolean;
  output_artifact_ids: string[];
  recovery_actions: string[];
  error_code: string | null;
}

export function videoTerminal(status: string): boolean {
  return ['succeeded', 'failed', 'cancelled', 'abandoned'].includes(status);
}
