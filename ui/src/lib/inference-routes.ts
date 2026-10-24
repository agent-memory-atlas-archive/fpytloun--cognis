export interface InferenceRouteConfig {
  name: string;
  targets: { provider_id: string; model: string; priority: number }[];
  recovery?: {
    max_retries_per_target: number;
    target_recovery_window_seconds: number;
    max_target_switches: number;
    request_timeout_seconds: number;
    failure_threshold: number;
    failure_window_seconds: number;
    cooldown_seconds: number;
  };
}

export interface InferenceRoute {
  route_id: string;
  revision: number;
  reference: string;
  owner_scope?: 'global' | 'user';
  config: InferenceRouteConfig;
}

export const defaultRecovery = {
  max_retries_per_target: 3,
  target_recovery_window_seconds: 30,
  max_target_switches: 8,
  request_timeout_seconds: 600,
  failure_threshold: 3,
  failure_window_seconds: 60,
  cooldown_seconds: 30,
};
