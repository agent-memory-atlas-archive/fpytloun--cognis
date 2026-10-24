import { describe, expect, it } from 'vitest';
import type { WorkflowStep } from '$lib/types/api';
import { syncHealthWorkflow } from '$lib/testing/workflow-plan-fixture';
import { plannedPhases, plannedStep } from './workflow-preview';

function preview(step: WorkflowStep) {
  return plannedStep({ ...syncHealthWorkflow(), steps: [step] }, step, 0);
}

describe('workflow plan preview', () => {
  it('explains blank-description deterministic steps without exposing raw tool arguments', () => {
    const workflow = syncHealthWorkflow();
    const steps = plannedPhases(workflow)[0].steps;
    expect(steps[0].summary).toBe('Synthetic catalog health probe');
    expect(steps[0].facts).toContain('Executor: synthetic-catalog-executor');
    expect(steps[0].facts).toContain('Side effects are permitted; this is not a read-only guarantee.');
    expect(JSON.stringify(steps[0])).not.toContain('printf');
    expect(steps[1].routes).toEqual([
      { label: 'If true', text: 'healthy' }, { label: 'If false', text: 'unhealthy' },
    ]);
    expect(steps[1].condition).toBe('{{ steps.probe.outputs.healthy == true }}');
    expect(steps[2].summary).toBe('The sample catalog requires attention.');
    expect(steps[2].facts).toContain('Send the result through the preferred channel.');
    expect(steps[3].facts).toContain('Finish silently; no completion message.');
    expect(steps[3].routes).toEqual([]);
  });

  it('uses nonblank descriptions first, then objectives, then prompt-only instructions', () => {
    expect(preview({ name: 'work', type: 'run', description: '  Overview  ', objective: 'Goal' }).summary).toBe('Overview');
    expect(preview({ name: 'work', type: 'run', description: ' \n ', objective: 'Goal' }).summary).toBe('Goal');
    const result = preview({
      name: 'work', type: 'run', description: '', prompt: 'Inspect all evidence.',
      objective: 'Report findings.', responsibilities: ['Check sources', 'Verify claims'],
      defer_to: ['Publishing'], agent_override: 'laforge', require_deliverable: false,
    });
    expect(result.facts).toContain('Agent: laforge');
    expect(result.facts).toContain('Verify claims');
    expect(result.details).toContainEqual({ label: 'Full instructions', text: 'Inspect all evidence.' });
    expect(result.details).toContainEqual({ label: 'Deferred responsibilities', text: 'Publishing' });
    expect(preview({ name: 'work', type: 'run', prompt: 'Inspect all evidence.' }).summary).toBe('Inspect all evidence.');
  });

  it('explains approval choices, gate conditions, and timeouts', () => {
    const step: WorkflowStep = {
      name: 'approve', type: 'gate', description: '',
      gate: {
        message: 'Approve deployment?',
        options: [{ label: 'Revise', action: 'revise(plan)' }, { label: 'Stop', action: 'cancel' }],
        conditions: [{ expression: 'needs_review' }],
        timeout_seconds: 600, timeout_action: 'cancel',
      },
    };
    const result = plannedStep(syncHealthWorkflow(), step, 0, { interactionMode: 'explicit_gates' });
    expect(result.summary).toBe('Approve deployment?');
    expect(result.routes).toEqual([
      { label: 'Revise', text: 'Return to plan for revision' },
      { label: 'Stop', text: 'Cancel the task' },
    ]);
    expect(result.facts).toContain('Without a response after 600 seconds: Cancel the task.');
    expect(result.details.some((item) => item.label === 'Gate conditions')).toBe(true);
  });

  it('shows explicit jumps and skip paths without claiming terminal outcomes always run', () => {
    const workflow = syncHealthWorkflow();
    workflow.steps[0].next = 'healthy';
    workflow.steps[0].when = '{{ enabled }}';
    expect(plannedPhases(workflow)[0].steps[0].routes).toEqual([
      { label: 'After this action', text: 'healthy' },
      { label: 'If skipped', text: 'healthy' },
    ]);
    const complete = preview({
      name: 'finish', type: 'complete', when: '{{ enabled }}',
      complete: { status: 'failed', summary: 'Checks failed.' },
    });
    expect(complete.facts).toContain('End the task as failed.');
    expect(complete.routes).toEqual([{ label: 'If skipped', text: 'End of workflow' }]);
  });

  it('uses definition fallthrough for omitted condition branches, not step.next', () => {
    const workflow = syncHealthWorkflow();
    workflow.steps[1].condition = { if: '{{ check }}', then: 'healthy' };
    workflow.steps[1].next = 'healthy';
    expect(plannedPhases(workflow)[0].steps[1].routes[1]).toEqual({ label: 'If false', text: 'unhealthy' });
  });

  it('does not claim a successful run advances when it has an explicit outcome route', () => {
    const result = preview({
      name: 'review', type: 'run', objective: 'Check the implementation.',
      outcome_routes: [{ status: 'success', action: 'gate' }, { status: 'rejected', action: 'revise(plan)' }],
    });
    expect(result.routes).toEqual([
      { label: 'On success', text: 'Pause for review' },
      { label: 'On rejected', text: 'Return to plan for revision' },
    ]);
  });

  it('respects explicit argument redaction and avoids interpreting command contents', () => {
    const result = preview({
      name: 'call', type: 'tool_call', tool_call: {
        tool: 'bash', redact_args: ['DESCRIPTION', 'target_executor'],
        args: { description: 'Private description', target_executor: 'private-host', token: 'secret-value', command: 'private command' },
      },
    });
    expect(result.summary).toBe('Call bash.');
    expect(JSON.stringify(result)).not.toMatch(/Private description|private-host|secret-value|private command/);
  });

  it('keeps long prompt-only instructions in disclosure and uses explicit completion model defaults', () => {
    const prompt = 'Verify each source carefully. '.repeat(30);
    const workflow = syncHealthWorkflow();
    const step: WorkflowStep = { name: 'work', type: 'run', prompt, completion: { evaluate: true } };
    const result = plannedStep(workflow, step, 0);
    expect(result.summary.length).toBeLessThan(prompt.length);
    expect(result.details).toContainEqual({ label: 'Full instructions', text: prompt.trim() });
    const completion = JSON.parse(result.details.find((item) => item.label === 'Completion checks')!.text);
    expect(completion).toEqual({ evaluate: true, max_attempts: 3, on_exhausted: 'gate' });
  });

  it('uses execution retry defaults when workflow evaluation is disabled', () => {
    const workflow = syncHealthWorkflow();
    const result = plannedStep(workflow, { name: 'work', type: 'run', objective: 'Check evidence.' }, 0);
    const completion = JSON.parse(result.details.find((item) => item.label === 'Completion checks')!.text);
    expect(completion).toEqual({ evaluate: false, max_attempts: 3, on_exhausted: 'gate' });
    workflow.defaults.evaluate = true;
    const evaluated = plannedStep(workflow, { name: 'work', type: 'run', objective: 'Check evidence.' }, 0);
    expect(JSON.parse(evaluated.details.find((item) => item.label === 'Completion checks')!.text).max_attempts).toBe(1);
  });

  it('explains autonomous gate bypass, including schedule overrides of workflow policy', () => {
    const workflow = syncHealthWorkflow();
    workflow.interaction = { mode: 'explicit_gates' };
    const step: WorkflowStep = { name: 'approve', type: 'gate', gate: {
      message: 'Approve recovery?', conditions: [{ expression: 'needs_review' }],
      options: [{ label: 'Approve', action: 'continue' }], timeout_seconds: 600,
    } };
    const result = plannedStep(workflow, step, 0, { interactionMode: 'none' });
    expect(result.facts.join(' ')).toContain('Autonomous mode bypasses this gate');
    expect(result.facts.join(' ')).not.toContain('Without a response');
    expect(result.routes).toEqual([{ label: 'Continue to', text: 'route' }]);
    expect(result.details.some((item) => item.label === 'Bypassed approval choices')).toBe(true);
  });

  it('resolves silent notification and task policy before the delivery destination', () => {
    const workflow = syncHealthWorkflow();
    const step: WorkflowStep = { name: 'finish', type: 'complete', complete: {
      summary: 'Finished.', delivery_mode_override: 'preferred_channel',
      notification: { mode: 'silent', reason: 'Nothing changed.' },
    } };
    expect(plannedStep(workflow, step, 0).facts).toContain('Finish silently; no completion message.');
    expect(plannedStep(workflow, step, 0).facts.join(' ')).not.toContain('preferred channel');
    step.complete!.notification = null;
    expect(plannedStep(workflow, step, 0, { allowSilentCompletion: true }).facts).toContain('Finish silently; no completion message.');
    step.complete!.notification = { mode: 'direct' };
    expect(plannedStep(workflow, step, 0, { allowSilentCompletion: true }).facts).toContain('Send the result through the preferred channel.');
    step.complete!.notification = { mode: 'silent', reason: 'Nothing changed.' };
    step.complete!.status = 'failed';
    expect(plannedStep(workflow, step, 0, { allowSilentCompletion: true }).facts).toContain('Send the result through the preferred channel.');
  });

  it('preserves authored phase grouping and step order', () => {
    const workflow = syncHealthWorkflow();
    workflow.presentation = { phases: [
      { id: 'check', title: 'Check health', description: 'Probe and route.', step_names: ['probe', 'route'] },
      { id: 'result', title: 'Possible results', description: '', step_names: ['unhealthy', 'healthy'] },
    ] };
    expect(plannedPhases(workflow).map((phase) => [phase.title, phase.steps.map((step) => step.name)])).toEqual([
      ['Check health', ['probe', 'route']], ['Possible results', ['unhealthy', 'healthy']],
    ]);
  });
});
