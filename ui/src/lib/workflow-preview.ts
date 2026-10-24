import type { Workflow, WorkflowStep } from '$lib/types/api';

export interface PreviewDetail {
  label: string;
  text: string;
}

export interface PlannedStep {
  name: string;
  kind: string;
  summary: string;
  condition: string;
  facts: string[];
  routes: PreviewDetail[];
  details: PreviewDetail[];
}

export interface PlannedPhase {
  id: string;
  title: string;
  description: string;
  steps: PlannedStep[];
}

export interface WorkflowPreviewContext {
  interactionMode?: string;
  allowSilentCompletion?: boolean;
  deliveryMode?: string;
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(text).filter(Boolean) : [];
}

function json(value: unknown): string {
  return value == null ? '' : JSON.stringify(value, null, 2);
}

function detail(details: PreviewDetail[], label: string, value: unknown): void {
  const content = text(value);
  if (content && content !== '{}' && content !== '[]') details.push({ label, text: content });
}

const kinds: Record<string, string> = {
  run: 'Agent work',
  gate: 'Review / approval',
  tool_call: 'Tool action',
  condition: 'Decision',
  complete: 'Outcome',
};

const deliveries: Record<string, string> = {
  silent: 'Finish silently; no completion message.',
  same_conversation: 'Send the result to the originating conversation.',
  preferred_channel: 'Send the result through the preferred channel.',
  latest_active_for_agent: 'Send the result to the agent’s latest active conversation.',
  specific_conversation: 'Send the result to the configured conversation.',
};

function actionLabel(value: unknown): string {
  const action = text(value);
  const target = /^revise\((.+)\)$/.exec(action)?.[1];
  if (target) return `Return to ${target} for revision`;
  const actions: Record<string, string> = {
    continue: 'Continue',
    cancel: 'Cancel the task',
    fail: 'Fail the task',
    gate: 'Pause for review',
  };
  return actions[action] ?? action;
}

function safeToolArgument(step: WorkflowStep, key: string): string {
  // Only descriptive fields are admitted. Never expose commands, payloads,
  // credentials, or a field explicitly marked for redaction.
  const redacted = (step.tool_call?.redact_args ?? []).map((path) => path.toLowerCase());
  if (redacted.some((path) => path === key || path.startsWith(`${key}.`) || path === '*')) return '';
  return text(step.tool_call?.args?.[key]);
}

export function plannedStep(
  workflow: Workflow, step: WorkflowStep, index: number, context: WorkflowPreviewContext = {},
): PlannedStep {
  const facts: string[] = [];
  const routes: PreviewDetail[] = [];
  const details: PreviewDetail[] = [];
  const next = workflow.steps[index + 1]?.name;
  const autonomous = (context.interactionMode ?? text(workflow.interaction?.mode)) === 'none';
  const destination = (target: unknown): string =>
    text(target) || next || 'End of workflow';
  let fallback = 'No instructions were provided for this step.';

  if (step.type === 'tool_call') {
    const tool = step.tool_call;
    fallback = safeToolArgument(step, 'description') || text(tool?.summary) ||
      `Call ${tool?.tool ?? 'the configured tool'}.`;
    facts.push(`Tool: ${tool?.tool ?? 'Not specified'}`);
    const executor = safeToolArgument(step, 'target_executor');
    if (executor) facts.push(`Executor: ${executor}`);
    facts.push(tool?.allow_side_effects
      ? 'Side effects are permitted; this is not a read-only guarantee.'
      : 'Side-effecting tools are not permitted.');
    facts.push(`On error: ${actionLabel(step.on_error ?? 'fail')}.`);
    if (tool?.fail_on_error === false) facts.push('Tool error results do not automatically fail this step.');
    if (tool?.timeout_seconds) facts.push(`Time limit: ${tool.timeout_seconds} seconds.`);
    routes.push({ label: 'After this action', text: destination(step.next) });
    detail(details, 'Output summary template', tool?.summary);
    detail(details, 'Output mapping', json(tool?.outputs));
  } else if (step.type === 'condition') {
    fallback = 'Evaluate the condition below and follow the matching path.';
    routes.push(
      { label: 'If true', text: destination(step.condition?.then) },
      { label: 'If false', text: destination(step.condition?.else) },
    );
    if (step.condition?.max_loop_iterations) {
      facts.push(`Revision limit: ${step.condition.max_loop_iterations}; then ${actionLabel(step.condition.on_exhausted ?? 'gate').toLowerCase()}.`);
    }
    detail(details, 'Decision output', json(step.condition?.output));
    detail(details, 'Revision source', step.condition?.revision_source);
  } else if (step.type === 'complete') {
    fallback = text(step.complete?.summary) || 'Finish the workflow.';
    facts.push(step.complete?.status === 'failed' ? 'End the task as failed.' : 'End the task as completed.');
    const notification = record(step.complete?.notification);
    const allowSilent = context.allowSilentCompletion ?? record(workflow.defaults?.delivery).allow_silent_completion === true;
    const silent = step.complete?.status !== 'failed' &&
      (notification.mode === 'silent' || (!notification.mode && allowSilent));
    const deliveryMode = text(step.complete?.delivery_mode_override) || context.deliveryMode || '';
    facts.push(silent || deliveryMode === 'silent'
      ? deliveries.silent
      : deliveries[deliveryMode] || 'Use the task’s configured delivery destination.');
    detail(details, 'Result summary', step.complete?.summary);
    detail(details, 'Result message', step.complete?.content);
    detail(details, 'Structured result', json(step.complete?.outputs));
    detail(details, 'Notification reason', notification.reason);
  } else if (step.type === 'gate') {
    const gate = record(step.gate);
    fallback = text(gate.message) || 'Review the previous work before continuing.';
    facts.push(autonomous
      ? 'Continue automatically. Autonomous mode bypasses this gate, including its conditions and approval choices.'
      : Array.isArray(gate.conditions) && gate.conditions.length > 0
      ? 'Pause for review only when the gate conditions require it.'
      : 'Pause and wait for a review response.');
    if (autonomous) routes.push({ label: 'Continue to', text: destination(null) });
    if (!autonomous && Array.isArray(gate.options)) {
      for (const option of gate.options) {
        const config = record(option);
        routes.push({ label: text(config.label) || 'Option', text: actionLabel(config.action) });
      }
    }
    if (!autonomous && typeof gate.timeout_seconds === 'number') {
      facts.push(`Without a response after ${gate.timeout_seconds} seconds: ${actionLabel(gate.timeout_action ?? 'fail')}.`);
    }
    detail(details, 'Review message', gate.message);
    detail(details, 'Gate conditions', json(gate.conditions));
    detail(details, 'Gate thresholds', json(gate.thresholds));
    detail(details, 'Review inputs', json(gate.input));
    if (autonomous) detail(details, 'Bypassed approval choices', json(gate.options));
  } else if (step.type === 'run') {
    const prompt = text(step.prompt);
    fallback = text(step.objective) || (prompt.length > 280 ? `${prompt.slice(0, 280)}…` : prompt) || fallback;
    facts.push(step.agent_override ? `Agent: ${step.agent_override}` : 'Agent: the task’s assigned agent.');
    if (step.agent_profile_id) facts.push(`Profile: ${step.agent_profile_id}`);
    facts.push(...strings(step.responsibilities));
    if (step.require_deliverable !== false) facts.push('Produce a deliverable.');
    if (step.allow_questions) facts.push(autonomous
      ? 'Questions are disabled by autonomous mode.'
      : 'May ask questions if the task’s interaction policy permits.');
    if (!(step.outcome_routes ?? []).some((route) => route.status === 'success')) {
      routes.push({ label: 'After success', text: destination(null) });
    }
    for (const route of step.outcome_routes ?? []) {
      routes.push({ label: `On ${text(route.status)}`, text: actionLabel(route.action) });
    }
    if (text(step.on_reject?.target)) {
      routes.push({ label: 'If rejected by review', text: `Return to ${step.on_reject?.target}` });
    }
    detail(details, 'Objective', step.objective);
    detail(details, 'Full instructions', step.prompt);
    detail(details, 'Deferred responsibilities', strings(step.defer_to).join('\n'));
    detail(details, 'Input context', json(step.input));
    const completion = record(step.completion);
    const defaults = record(workflow.defaults);
    // Explicit completion configs have their own model defaults. When workflow
    // evaluation is disabled, execution failure retries still default to three.
    const explicit = step.completion != null;
    const evaluate = explicit ? completion.evaluate ?? true : defaults.evaluate ?? true;
    detail(details, 'Completion checks', json({
      evaluate,
      max_attempts: explicit ? completion.max_attempts ?? 3 : evaluate ? defaults.max_attempts ?? 3 : 3,
      on_exhausted: explicit ? completion.on_exhausted ?? 'gate' : defaults.on_exhausted ?? 'gate',
      evaluator_prompt: completion.evaluator_prompt,
    }));
    detail(details, 'Rejection handling', json(step.on_reject));
    detail(details, 'Outcome routing', json(step.outcome_routes));
  }

  if (text(step.when)) {
    facts.unshift('Runs only when its entry condition is true; otherwise it is skipped.');
    detail(details, 'Entry condition', step.when);
    detail(details, 'Skipped result', json(step.on_skip));
    routes.push({ label: 'If skipped', text: destination(step.next) });
  }
  detail(details, 'Error handling', step.on_error);
  const summary = text(step.description) || text(step.objective) || fallback;
  return {
    name: step.name,
    kind: kinds[step.type] ?? step.type,
    summary,
    condition: text(step.condition?.if),
    facts,
    routes,
    details: details.filter((item) => item.text !== summary),
  };
}

export function plannedPhases(workflow: Workflow, context: WorkflowPreviewContext = {}): PlannedPhase[] {
  const steps = workflow.steps.map((step, index) => plannedStep(workflow, step, index, context));
  const phases = workflow.presentation?.phases ?? [];
  if (phases.length === 0) {
    return [{ id: 'workflow', title: '', description: '', steps }];
  }
  const byName = new Map(steps.map((step) => [step.name, step]));
  return phases.map((phase) => ({
    id: phase.id,
    title: phase.title,
    description: text(phase.description),
    steps: phase.step_names.flatMap((name) => {
      const step = byName.get(name);
      return step ? [step] : [];
    }),
  }));
}
