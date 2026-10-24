import { writable } from 'svelte/store';

import { api } from '$lib/api/client';
import type { Deliverable, DeliverableRevisionSummary } from '$lib/types/api';

/**
 * Highest revision seen per lineage among deliverables rendered in this
 * window. A mounted card for an older revision compares against it to learn
 * that a newer revision was published after it loaded.
 */
export const observedLineageRevisions = writable<Record<string, number>>({});

export function observeLineageRevision(
  lineageId: string | null | undefined,
  revision: number | null | undefined,
): void {
  if (!lineageId || !revision) return;
  observedLineageRevisions.update((current) =>
    (current[lineageId] ?? 0) >= revision ? current : { ...current, [lineageId]: revision },
  );
}

/** Whether a loaded deliverable belongs to a lineage with more than one live revision. */
export function hasRevisionHistory(deliverable: Pick<Deliverable, 'revision_count' | 'revision'> | null | undefined): boolean {
  if (!deliverable) return false;
  return (deliverable.revision_count ?? 1) > 1 || (deliverable.revision ?? 1) > 1;
}

/** Whether a loaded deliverable has been replaced by a newer live revision. */
export function isSupersededRevision(deliverable: Pick<Deliverable, 'is_latest'> | null | undefined): boolean {
  return deliverable?.is_latest === false;
}

/**
 * Load one revision through the detail endpoint that owns its access rules:
 * task outputs through their step run, conversation deliverables directly.
 */
export function loadDeliverableRevision(
  revision: Pick<DeliverableRevisionSummary, 'deliverable_id' | 'step_run_id'>,
  options: { accessorConversationId?: string } = {},
): Promise<Deliverable> {
  return revision.step_run_id
    ? api.deliverables.getForStepRun(revision.step_run_id, revision.deliverable_id)
    : api.deliverables.get(revision.deliverable_id, options);
}

export function revisionLabel(revision: number | null | undefined, total: number | null | undefined): string {
  const current = revision ?? 1;
  return total && total > 1 ? `Revision ${current} of ${total}` : `Revision ${current}`;
}
