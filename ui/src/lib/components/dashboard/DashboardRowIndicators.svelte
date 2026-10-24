<script lang="ts">
  import Star from 'lucide-svelte/icons/star';
  import ConversationProjectBadge from '$lib/components/projects/ConversationProjectBadge.svelte';
  import WorkstreamTodoProgress from '$lib/components/WorkstreamTodoProgress.svelte';
  import type { Conversation, Project } from '$lib/types/api';

  type Identity = Pick<Conversation, 'project_id' | 'project_name' | 'project_color' | 'project_avatar_url' | 'project_icon'>;
  let {
    item, projects = [], selectedProjectId = '', onToggleProject,
    progress, starred = false, onToggleStar, active = false,
  } = $props<{
    item: Identity; projects?: Project[]; selectedProjectId?: string;
    onToggleProject?: (id: string) => void;
    progress?: { total: number; completed: number; in_progress: number };
    starred?: boolean; active?: boolean; onToggleStar?: () => void;
  }>();
  const project = $derived(projects.find((entry: Project) => entry.project_id === item.project_id));
  const identity = $derived<Identity>(project ? {
    project_id: project.project_id, project_name: project.name, project_color: project.color,
    project_avatar_url: project.avatar_url,
    project_icon: typeof project.metadata?.icon === 'string' ? project.metadata.icon : null,
  } : item);
</script>

<div class="grid shrink-0 grid-cols-[auto_minmax(1.5rem,auto)] items-center gap-0.5" data-testid="dashboard-row-indicators">
  <div class="col-start-2 row-start-1 flex justify-center">
    <ConversationProjectBadge conversation={identity} selected={selectedProjectId === identity.project_id}
      onToggle={onToggleProject && identity.project_id ? () => onToggleProject?.(identity.project_id!) : undefined} />
  </div>
  <div class="col-start-1 row-start-2 flex items-center justify-center gap-0.5">
    {#if progress}<WorkstreamTodoProgress {progress} />{/if}
  </div>
  {#if starred || (active && onToggleStar)}
    <button type="button" disabled={!onToggleStar} aria-label={starred ? 'Unstar conversation' : 'Star conversation'}
      class="col-start-2 row-start-2 justify-self-center rounded-lg p-1 text-quiet hover:text-warning"
      onclick={(event) => { event.stopPropagation(); onToggleStar?.(); }} onkeydown={(event) => event.stopPropagation()}>
      <Star class={`h-4 w-4 ${starred ? 'fill-warning text-warning' : ''}`} />
    </button>
  {/if}
</div>
