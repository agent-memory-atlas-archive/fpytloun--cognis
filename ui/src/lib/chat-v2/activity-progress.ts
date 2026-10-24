import type { RuntimeOverlaySnapshot } from './types';
import type { TimelineRow } from './tool-groups';

/** Keep the tail activity alive across tool completion and thinking cycles. */
export function activeActivityGroupId(
  rows: readonly TimelineRow[],
  runtime: RuntimeOverlaySnapshot | null | undefined,
): string | null {
  const turn = runtime?.active_turn;
  if (!runtime?.has_active_turn || !turn || turn.retry_at
    || (turn.status !== 'running' && turn.status !== 'starting')) return null;
  if (runtime.authority && !['active', 'legacy'].includes(runtime.authority.lifecycle)) return null;

  for (let index = rows.length - 1; index >= 0; index--) {
    const row = rows[index];
    if (row.kind === 'thinking_group' || (row.kind === 'item' && row.item.kind === 'thinking')) continue;
    if (row.kind !== 'tool_group' && row.kind !== 'activity_segment') return null;
    const tools = row.kind === 'tool_group' ? row.items : row.toolGroups.flatMap((group) => group.items);
    // A recoverable tool failure remains styled as failed, but does not stop
    // the owning turn's progress while it thinks or tries another tool.
    return tools.at(-1)?.turn_id === turn.turn_id ? row.id : null;
  }
  return null;
}
