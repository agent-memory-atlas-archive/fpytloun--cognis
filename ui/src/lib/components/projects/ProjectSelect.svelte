<script lang="ts">
  import type { Project } from '$lib/types/api';

  let {
    projects,
    value = $bindable(''),
    label = 'Project',
    disabled = false,
    noneLabel = 'No project',
    id = 'project-select',
    onchange,
  } = $props<{
    projects: Project[];
    value?: string;
    label?: string;
    disabled?: boolean;
    noneLabel?: string;
    id?: string;
    onchange?: (projectId: string) => void;
  }>();

  // Only roles that may add work are selectable (viewers can only read).
  const selectable = $derived(
    projects.filter(
      (project: Project) =>
        project.status === 'active' && (project.caller_role ?? 'owner') !== 'viewer'
    )
  );

  function sharedSuffix(project: Project): string {
    if (project.is_shared_with_me) return ' · shared with you';
    const members = (project.grants ?? []).filter((grant) => !grant.revoked_at).length;
    return members > 0 ? ` · shared with ${members}` : '';
  }
</script>

<label class="block space-y-1" for={id}>
  <span class="block text-xs font-medium uppercase tracking-widest text-quiet">{label}</span>
  <select
    {id}
    bind:value
    class="w-full rounded-xl border border-control-border bg-canvas/80 px-3 py-2 text-sm text-foreground"
    {disabled}
    onchange={() => onchange?.(value)}
  >
    <option value="">{noneLabel}</option>
    {#each selectable as project (project.project_id)}
      <option value={project.project_id}>{project.name}{sharedSuffix(project)}</option>
    {/each}
  </select>
</label>
