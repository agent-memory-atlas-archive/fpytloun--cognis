<script lang="ts">
  import { FolderKanban, Lock, Users } from 'lucide-svelte';
  import { keepInViewport } from '$lib/actions/keep-in-viewport';

  import type { Conversation, Project, ProjectGrant, ResourceVisibility } from '$lib/types/api';

  let {
    conversation,
    projects,
    busy = false,
    onchangeProject,
    onchangeVisibility,
  } = $props<{
    conversation: Conversation;
    projects: Project[];
    busy?: boolean;
    onchangeProject: (projectId: string | null) => void;
    onchangeVisibility: (visibility: ResourceVisibility) => void;
  }>();

  let open = $state(false);

  const project = $derived(
    projects.find((item: Project) => item.project_id === conversation.project_id) ?? null
  );
  const readonly = $derived(Boolean(conversation.is_readonly_for_caller));
  const assignable = $derived(conversation.project_assignable !== false && !readonly);
  const sharedProject = $derived(
    project !== null
      && (project.is_shared_with_me || (project.grants ?? []).some((grant: ProjectGrant) => !grant.revoked_at))
  );
  const memberCount = $derived(
    project ? (project.grants ?? []).filter((grant: ProjectGrant) => !grant.revoked_at).length + 1 : 0
  );
  const choices = $derived(
    projects.filter(
      (item: Project) => item.status === 'active' && (item.caller_role ?? 'owner') !== 'viewer'
    )
  );

  function choose(projectId: string | null): void {
    open = false;
    if (projectId === (conversation.project_id ?? null)) return;
    onchangeProject(projectId);
  }
</script>

{#if project || assignable}
  <div class="relative flex min-w-0 max-w-full flex-wrap items-center gap-1.5" data-testid="conversation-project-control">
    <button
      type="button"
      class="flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-violet-border bg-violet-subtle px-2 py-0.5 text-[11px] font-medium text-violet-tone transition hover:border-violet-border disabled:cursor-default disabled:opacity-80"
      disabled={!assignable || busy}
      onclick={() => { open = !open; }}
      aria-haspopup="listbox"
      aria-expanded={open}
      title={assignable ? 'Change project' : 'Project'}
      data-testid="conversation-project-chip"
    >
      <FolderKanban class="h-3 w-3" />
      <span class="max-w-[12rem] truncate">{project ? project.name : 'No project'}</span>
    </button>

    <!-- Always reachable for project chats: sharing covers current and future members. -->
    {#if project}
      {#if conversation.visibility === 'private'}
        <button
          type="button"
          class="flex items-center gap-1 rounded-full border border-control-border bg-raised/70 px-2 py-0.5 text-[11px] text-secondary transition hover:border-border-strong disabled:cursor-default"
          disabled={readonly || busy}
          onclick={() => onchangeVisibility('project')}
          title={readonly ? 'Private conversation' : 'Only you can see this chat. Click to share it with the project.'}
          data-testid="conversation-visibility-private"
        >
          <Lock class="h-3 w-3" /> Private
        </button>
      {:else}
        <button
          type="button"
          class="flex items-center gap-1 rounded-full border border-success-border bg-success-subtle px-2 py-0.5 text-[11px] text-success transition hover:border-success-border disabled:cursor-default"
          disabled={readonly || busy}
          onclick={() => onchangeVisibility('private')}
          title={readonly ? 'Shared with project members' : 'Project members can read this chat. Click to make it private.'}
          data-testid="conversation-visibility-project"
        >
          <Users class="h-3 w-3" /> {sharedProject ? `Shared · ${memberCount} ${memberCount === 1 ? 'person' : 'people'}` : 'Shared with project'}
        </button>
      {/if}
    {/if}

    {#if open}
      <div class="absolute left-0 top-full z-40 mt-1 max-h-72 w-64 max-w-full overflow-y-auto rounded-xl border border-control-border bg-canvas p-1 shadow-xl shadow-black/40" role="listbox" use:keepInViewport>
        <button
          type="button"
          class="flex w-full rounded-lg px-2.5 py-2 text-left text-xs text-secondary hover:bg-surface"
          role="option"
          aria-selected={!conversation.project_id}
          onclick={() => choose(null)}
        >No project</button>
        {#each choices as item (item.project_id)}
          <button
            type="button"
            class={`flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-xs ${item.project_id === conversation.project_id ? 'bg-violet-subtle text-violet-tone' : 'text-foreground hover:bg-surface'}`}
            role="option"
            aria-selected={item.project_id === conversation.project_id}
            onclick={() => choose(item.project_id)}
          >
            <span class="truncate">{item.name}</span>
            {#if item.is_shared_with_me || (item.grants ?? []).some((grant: ProjectGrant) => !grant.revoked_at)}
              <Users class="h-3 w-3 shrink-0 text-quiet" />
            {/if}
          </button>
        {/each}
      </div>
    {/if}
  </div>
{/if}
