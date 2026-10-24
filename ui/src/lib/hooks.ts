/** Shared hook API contracts. */
export type HookTrigger = 'first_user_message' | 'user_message' | 'before_turn' |
  'before_model_cycle' | 'turn_completed' | 'conversation_idle';
export interface HookDefinition {
  name: string;
  description: string;
  trigger: HookTrigger;
  condition: string | null;
  idle_seconds: number;
  action: 'prompt' | 'tool_call';
  mode: 'inject' | 'fork' | 'fresh' | 'follow_up';
  prompt: string;
  tool_call: {
    tool: string;
    args?: Record<string, unknown>;
    summary?: string | null;
    timeout_seconds?: number;
    allow_side_effects?: boolean;
  } | null;
  parameters: Record<string, unknown>;
  timeout_seconds: number;
}
export interface AgentHook extends HookDefinition {
  hook_id: string;
  revision: number;
  bundled: boolean;
}
export interface HookAssignment {
  hook_id: string;
  enabled: boolean;
  parameters: Record<string, unknown>;
}
export interface HookRun {
  run_id: string;
  hook_id: string;
  hook_revision: number;
  agent_id: string;
  conversation_id: string;
  status: string;
  child_conversation_id: string | null;
  task_id: string | null;
  created_at: string;
  finished_at: string | null;
}
export const hookTriggers: HookTrigger[] = [
  'first_user_message', 'user_message', 'before_turn', 'before_model_cycle',
  'turn_completed', 'conversation_idle'
];
export function emptyHook(): HookDefinition {
  return {
    name: '', description: '', trigger: 'user_message', condition: null,
    idle_seconds: 900, action: 'prompt', mode: 'inject', prompt: '', tool_call: null,
    parameters: {}, timeout_seconds: 600
  };
}
export function hookDefinition(hook: AgentHook): HookDefinition {
  const { hook_id: _id, revision: _revision, bundled: _bundled, ...definition } = hook;
  return JSON.parse(JSON.stringify(definition));
}

export const hookTriggerLabels: Record<HookTrigger, string> = {
  first_user_message: 'First message', user_message: 'User message',
  before_turn: 'Before a turn', before_model_cycle: 'Before each model cycle',
  turn_completed: 'After a turn', conversation_idle: 'When idle'
};
export const hookModeLabels: Record<HookDefinition['mode'], string> = {
  inject: 'Context reminder', fork: 'Background fork',
  fresh: 'Fresh execution', follow_up: 'Follow-up turn'
};
export const hookModeDescriptions: Record<HookDefinition['mode'], string> = {
  inject: 'Adds instructions before the next model response. No separate run.',
  fork: 'Runs in the background with a snapshot of the conversation.',
  fresh: 'Runs independently without copying conversation history.',
  follow_up: 'Queues a separate automated turn in the same conversation.'
};
export function hookTriggerSummary(hook: HookDefinition): string {
  if (hook.trigger !== 'conversation_idle') return hookTriggerLabels[hook.trigger];
  const minutes = hook.idle_seconds / 60;
  return `After ${Number.isInteger(minutes) ? minutes : minutes.toFixed(1)} min idle`;
}
