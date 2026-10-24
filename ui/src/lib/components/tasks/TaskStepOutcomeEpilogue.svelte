<script lang="ts">
  import AssistantDeliverableBlock from '$lib/components/AssistantDeliverableBlock.svelte';
  import { api } from '$lib/api/client';
  import { renderMarkdown } from '$lib/markdown';
  import type { AssistantDeliverableTimelineItem } from '$lib/timeline-render-model';
  import type { Deliverable, StepRun } from '$lib/types/api';

  let { stepRun } = $props<{ stepRun: StepRun }>();

  const deliverable = $derived(stepRun.deliverables?.[0] ?? null);
  const deliverableItem = $derived.by<AssistantDeliverableTimelineItem | null>(() => {
    if (!deliverable) return null;
    return {
      id: `step-deliverable:${stepRun.step_run_id}:${deliverable.deliverable_id}`,
      kind: 'assistant_deliverable',
      deliverableId: deliverable.deliverable_id,
      format: deliverable.format,
      title: deliverable.title,
      content: deliverable.content,
      createdAt: deliverable.created_at ?? undefined,
      updatedAt: deliverable.updated_at ?? undefined,
    };
  });
  const evaluationDecision = $derived(stringValue(stepRun.evaluation?.decision));
  const evaluationReasoning = $derived(stringValue(stepRun.evaluation?.reasoning));
  const evaluationFeedback = $derived(stringValue(stepRun.evaluation?.feedback));
  const summary = $derived(stringValue(stepRun.output?.summary));
  const content = $derived(stringValue(stepRun.output?.content));
  const error = $derived(stringValue(stepRun.output?.error));
  const claims = $derived.by<string[]>(() => {
    const values: unknown = stepRun.output?.claims;
    return Array.isArray(values)
      ? values.filter((claim: unknown): claim is string => typeof claim === 'string')
      : [];
  });
  const outcome = $derived(recordValue(stepRun.output?.outcome));
  const outcomeStatus = $derived(stringValue(outcome.status));
  const outcomeReason = $derived(stringValue(outcome.reason));
  const evaluating = $derived(stepRun.status === 'evaluating');
  const hasMetadata = $derived(
    evaluating || evaluationDecision || evaluationReasoning || evaluationFeedback ||
    summary || content || error || claims.length > 0 || outcomeStatus || outcomeReason
  );

  function stringValue(value: unknown): string {
    return typeof value === 'string' ? value : '';
  }

  function recordValue(value: unknown): Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
      ? value as Record<string, unknown>
      : {};
  }

  function loadStepDeliverable(deliverableId: string): Promise<Deliverable> {
    return api.deliverables.getForStepRun(stepRun.step_run_id, deliverableId);
  }
</script>

{#if deliverableItem || hasMetadata}
  <section
    class="mt-8 space-y-4 border-t border-separator/80 pt-6"
    data-testid="task-step-outcome"
    data-step-run-id={stepRun.step_run_id}
  >
    <div class="flex flex-wrap items-center justify-between gap-2">
      <p class="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">Task outcome</p>
      <div class="flex flex-wrap gap-2 text-[11px] uppercase tracking-wide">
        <span class="rounded-full border border-control-border bg-surface/70 px-2.5 py-1 text-secondary">{stepRun.status}</span>
        {#if deliverable}
          <span class="rounded-full border border-accent/30 bg-accent-subtle px-2.5 py-1 text-accent">
            Draft {deliverable.version} {deliverable.status}
          </span>
        {/if}
      </div>
    </div>

    {#if deliverableItem}
      {#key deliverableItem.deliverableId}
        <div data-kind="assistant_deliverable">
          <AssistantDeliverableBlock item={deliverableItem} loadDeliverable={loadStepDeliverable} />
        </div>
      {/key}
    {/if}

    {#if evaluating}
      <div class="rounded-xl border border-violet-border bg-violet-subtle px-4 py-3 text-sm text-violet-tone">
        Evaluator is reviewing this attempt…
      </div>
    {/if}

    {#if evaluationDecision || evaluationReasoning || evaluationFeedback}
      <div class="rounded-xl border border-control-border/80 bg-surface/60 px-4 py-3 text-sm text-secondary">
        <p class="text-xs font-medium uppercase tracking-widest text-quiet">Evaluation</p>
        {#if evaluationDecision}<p class="mt-2 font-medium text-strong">{evaluationDecision}</p>{/if}
        {#if evaluationReasoning}<div class="prose prose-sm prose-invert mt-2 max-w-none">{@html renderMarkdown(evaluationReasoning)}</div>{/if}
        {#if evaluationFeedback}<p class="mt-2 text-muted"><span class="font-medium">Feedback:</span> {evaluationFeedback}</p>{/if}
      </div>
    {/if}

    {#if summary}<div class="prose prose-sm prose-invert max-w-none text-secondary">{@html renderMarkdown(summary)}</div>{/if}
    {#if content && content.trim() !== deliverable?.content?.trim()}
      <div class="prose prose-sm prose-invert max-w-none text-secondary">{@html renderMarkdown(content)}</div>
    {/if}
    {#if outcomeStatus || outcomeReason}
      <p class="rounded-xl border border-control-border/80 bg-surface/50 px-4 py-3 text-sm text-secondary">
        {outcomeStatus || 'Outcome'}{#if outcomeReason}: {outcomeReason}{/if}
      </p>
    {/if}
    {#if claims.length > 0}
      <ul class="space-y-1 text-sm text-muted">
        {#each claims as claim}<li>• {claim}</li>{/each}
      </ul>
    {/if}
    {#if error}
      <pre class="whitespace-pre-wrap rounded-xl border border-danger-border bg-danger-subtle px-4 py-3 text-xs text-danger">{error}</pre>
    {/if}
  </section>
{/if}
