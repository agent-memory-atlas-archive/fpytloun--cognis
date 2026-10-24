<script lang="ts">
  import type { Workflow } from '$lib/types/api';
  import { plannedPhases, type WorkflowPreviewContext } from '$lib/workflow-preview';

  let { workflow, taskDescription = '', context = {} }: {
    workflow: Workflow; taskDescription?: string; context?: WorkflowPreviewContext;
  } = $props();
  const phases = $derived(plannedPhases(workflow, context));
  const agentWork = $derived(workflow.steps.some((step) => step.type === 'run'));
  const hasBranches = $derived(workflow.steps.some((step) =>
    step.type === 'condition' || step.when || step.next || (step.outcome_routes?.length ?? 0) > 0));
</script>

<div class="space-y-5 text-sm leading-6" data-testid="dashboard-schedule-planned-steps">
  <header class="space-y-2">
    <h3 class="font-medium text-strong">{workflow.name}</h3>
    {#if workflow.description?.trim()}
      <p class="whitespace-pre-wrap break-words text-secondary">{workflow.description}</p>
    {/if}
    {#if taskDescription.trim() && taskDescription.trim() !== workflow.description?.trim()}
      <details>
        <summary class="min-h-11 cursor-pointer py-2 text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">Scheduled task instructions</summary>
        <p class="whitespace-pre-wrap break-words text-secondary">{taskDescription}</p>
      </details>
    {/if}
    <p class="text-muted">
      {agentWork ? 'Includes agent work. Actions are chosen while the task runs.' : 'Defined actions and decisions; no AI work steps.'}
    </p>
    {#if hasBranches}
      <p class="text-muted">Shown in definition order, not a guaranteed execution sequence. Decisions select a path; not every step runs.</p>
    {/if}
  </header>

  {#if workflow.steps.length === 0}
    <p class="text-muted">This workflow has no planned steps.</p>
  {/if}
  {#each phases as phase (phase.id)}
    <section class="min-w-0 space-y-3">
      {#if phase.title}
        <h4 class="font-medium text-foreground">{phase.title}</h4>
        {#if phase.description}
          <p class="whitespace-pre-wrap break-words text-muted">{phase.description}</p>
        {/if}
      {/if}
      <ul class="space-y-3">
        {#each phase.steps as step (step.name)}
          <li class="min-w-0 rounded-xl border border-separator bg-surface/50 p-4" data-testid={`planned-step-${step.name}`}>
            <p class="text-xs font-medium uppercase tracking-wide text-accent">{step.kind}</p>
            <h5 class="mt-1 break-words font-medium text-strong">{step.name}</h5>
            <p class="mt-2 whitespace-pre-wrap break-words text-foreground">{step.summary}</p>
            {#if step.facts.length}
              <ul class="mt-3 space-y-1 text-muted">
                {#each step.facts as fact}
                  <li class="break-words">{fact}</li>
                {/each}
              </ul>
            {/if}
            {#if step.condition}
              <div class="mt-3">
                <p class="text-xs text-quiet">Condition</p>
                <code class="mt-1 block whitespace-pre-wrap break-all text-xs text-secondary">{step.condition}</code>
              </div>
            {/if}
            {#if step.routes.length}
              <dl class="mt-3 space-y-1 border-t border-separator pt-3 text-secondary">
                {#each step.routes as route}
                  <div class="flex flex-wrap gap-x-2">
                    <dt class="text-quiet">{route.label}:</dt>
                    <dd class="min-w-0 break-words">{route.text}</dd>
                  </div>
                {/each}
              </dl>
            {/if}
            {#if step.details.length}
              <details class="mt-3 border-t border-separator pt-1">
                <summary class="min-h-11 cursor-pointer py-2 text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">Instructions and technical details</summary>
                <dl class="space-y-3 pb-2">
                  {#each step.details as item}
                    <div>
                      <dt class="font-medium text-muted">{item.label}</dt>
                      <dd class="mt-1 whitespace-pre-wrap break-words text-xs leading-5 text-secondary">{item.text}</dd>
                    </div>
                  {/each}
                </dl>
              </details>
            {/if}
          </li>
        {/each}
      </ul>
    </section>
  {/each}
</div>
