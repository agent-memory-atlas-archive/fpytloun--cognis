<script lang="ts">
  import ArrowDown from 'lucide-svelte/icons/arrow-down';
  import ArrowUp from 'lucide-svelte/icons/arrow-up';
  import Bot from 'lucide-svelte/icons/bot';
  import CheckCircle from 'lucide-svelte/icons/check-circle';
  import GitBranch from 'lucide-svelte/icons/git-branch';
  import Hand from 'lucide-svelte/icons/hand';
  import Wrench from 'lucide-svelte/icons/wrench';

  import type { WorkflowPhaseFormState, WorkflowStepFormState } from '$lib/workflows';
  import { workflowStepSummary } from '$lib/workflows';

  export let phases: WorkflowPhaseFormState[] = [];
  export let steps: WorkflowStepFormState[] = [];
  export let selectedIndex = 0;
  export let disabled = false;
  export let onselect: (index: number) => void;
  export let onmove: (index: number, delta: -1 | 1) => void;
  export let onadd: (phaseId: string) => void;

  const accents: Record<WorkflowStepFormState['type'], string> = {
    run: 'border-l-success-border',
    gate: 'border-l-warning-border',
    tool_call: 'border-l-violet-border',
    condition: 'border-l-accent',
    complete: 'border-l-teal-border'
  };

  $: stepsByPhase = steps.reduce(
    (grouped, step, index) => {
      const phaseSteps = grouped.get(step.phaseId) ?? [];
      phaseSteps.push({ step, index });
      grouped.set(step.phaseId, phaseSteps);
      return grouped;
    },
    new Map<string, Array<{ step: WorkflowStepFormState; index: number }>>()
  );
</script>

<div class="space-y-4" data-testid="workflow-step-canvas">
  {#each phases as phase}
    <section class="rounded-2xl border border-separator bg-canvas/40 p-3" data-testid={`workflow-canvas-phase-${phase.id}`}>
      <div class="mb-2 flex items-center justify-between gap-2">
        <div class="min-w-0">
          <h3 class="truncate text-sm font-semibold text-foreground">{phase.title}</h3>
          {#if phase.description}<p class="truncate text-xs text-quiet">{phase.description}</p>{/if}
        </div>
        <button class="h-9 rounded-xl border border-control-border px-3 text-xs text-secondary hover:border-border-strong focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-40" type="button" disabled={disabled} onclick={() => onadd(phase.id)}>Add step</button>
      </div>
      <div class="space-y-2" role="list" aria-label={`${phase.title} steps`}>
        {#each stepsByPhase.get(phase.id) ?? [] as { step, index }}
            <div class="flex items-stretch gap-1">
              <button
                type="button"
                class={`min-w-0 flex-1 rounded-xl border border-l-4 px-3 py-2 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${accents[step.type]} ${selectedIndex === index ? 'border-accent/60 bg-accent-subtle' : 'border-separator bg-surface/70 hover:border-control-border'}`}
                aria-current={selectedIndex === index ? 'true' : undefined}
                data-testid={`workflow-step-card-${index}`}
                onclick={() => onselect(index)}
              >
                <span class="flex items-center gap-2">
                  {#if step.type === 'run'}<Bot class="h-4 w-4 text-success" aria-label="Agent step" />
                  {:else if step.type === 'gate'}<Hand class="h-4 w-4 text-warning" aria-label="Gate step" />
                  {:else if step.type === 'tool_call'}<Wrench class="h-4 w-4 text-violet-tone" aria-label="Tool step" />
                  {:else if step.type === 'condition'}<GitBranch class="h-4 w-4 text-accent" aria-label="Condition step" />
                  {:else}<CheckCircle class="h-4 w-4 text-teal-tone" aria-label="Complete step" />{/if}
                  <span class="truncate text-sm font-medium text-foreground">{step.name || `Step ${index + 1}`}</span>
                </span>
                <span class="mt-1 block truncate text-xs text-muted">{workflowStepSummary(step)}</span>
              </button>
              <div class="grid shrink-0 grid-rows-2">
                <button class="w-9 rounded-t-lg text-muted hover:bg-raised focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-30" aria-label={`Move ${step.name || `step ${index + 1}`} up`} disabled={disabled || index === 0} type="button" onclick={() => onmove(index, -1)}><ArrowUp class="mx-auto h-3.5 w-3.5" /></button>
                <button class="w-9 rounded-b-lg text-muted hover:bg-raised focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-30" aria-label={`Move ${step.name || `step ${index + 1}`} down`} disabled={disabled || index === steps.length - 1} type="button" onclick={() => onmove(index, 1)}><ArrowDown class="mx-auto h-3.5 w-3.5" /></button>
              </div>
            </div>
        {/each}
      </div>
    </section>
  {/each}
</div>
