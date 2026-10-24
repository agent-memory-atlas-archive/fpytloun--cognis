import type { ProjectTaskSummary, TaskBoard, TaskBoardItem } from '$lib/types/api';

/** Adapt readable project metadata, never another author's runtime projection. */
export function projectTaskBoard(tasks: ProjectTaskSummary[], projectId: string): TaskBoard {
  const board: TaskBoard = { columns: {} };
  for (const task of tasks) {
    // The shared section's Recent lane must also show queued/draft project work.
    const key = ['running', 'paused'].includes(task.status) ? task.status : 'done';
    const column = board.columns[key] ??= { items: [], groups: [], cursor: null, has_more: false, total_count: 0 };
    const item: TaskBoardItem = {
      ...task,
      title: task.title ?? task.task_id,
      agent_id: task.agent_id ?? '',
      project_id: projectId,
    };
    column.items.push(item);
    column.total_count++;
  }
  return board;
}
