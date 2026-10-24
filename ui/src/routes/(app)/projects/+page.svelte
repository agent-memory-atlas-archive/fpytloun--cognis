<script lang="ts">
  import { untrack, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { auth } from '$lib/stores/auth';
  import { lastProjectUrl } from '$lib/projects/navigation';
  import Clock from 'lucide-svelte/icons/clock';
  import ListTodo from 'lucide-svelte/icons/list-todo';
  import { api } from '$lib/api/client';
  import ProjectAvatar from '$lib/components/projects/ProjectAvatar.svelte';
  import ImageLightbox from '$lib/components/ImageLightbox.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import Card from '$lib/components/ui/Card.svelte';
  import Input from '$lib/components/ui/Input.svelte';
  import { scheduleListProjectUrl, taskBoardProjectUrl } from '$lib/tasks';
  import type { Project } from '$lib/types/api';
  import { useSectionConnectivity } from '$lib/connectivity-section.svelte';

  let projects = $state<Project[]>([]);
  let alive = true;
  let resumePending = true;
  let loading = $state(true);
  // Load errors are hidden while the global connection banner applies and
  // reload on restore; create errors always show.
  let loadError = $state<string | null>(null);
  let createError = $state<string | null>(null);
  let name = $state('');
  let description = $state('');
  let creating = $state(false);
  let profileProject = $state<Project | null>(null);
  let lightboxProject = $state<Project | null>(null);
  // Hidden while the global connection banner applies; reload on restore.
  const net = useSectionConnectivity({ hasError: () => Boolean(loadError), retry: load });
  const error = $derived(createError ?? (net.hideErrors ? null : loadError));

  async function load(): Promise<void> {
    loading = true;
    loadError = null;
    const requestedUrl = page.url.href;
    const email = auth.getSnapshot().user?.email;
    try {
      projects = await api.projects.list();
      if (alive && resumePending && page.url.href === requestedUrl && email === auth.getSnapshot().user?.email) {
        resumePending = false;
        if (page.url.searchParams.get('view') !== 'all') {
          const target = lastProjectUrl(email, projects.map((project) => project.project_id));
          if (target) await goto(target, { replaceState: true });
        }
      }
    } catch (err) {
      loadError = err instanceof Error ? err.message : 'Failed to load projects';
    } finally {
      loading = false;
    }
  }

  async function createProject(): Promise<void> {
    if (!name.trim()) return;
    creating = true;
    createError = null;
    try {
      const project = await api.projects.create({ name: name.trim(), description: description.trim() || null });
      name = '';
      description = '';
      await goto(`/projects/${project.project_id}`);
    } catch (err) {
      createError = err instanceof Error ? err.message : 'Failed to create project';
    } finally {
      creating = false;
    }
  }

  $effect(() => {
    void page.url.href;
    untrack(() => {
      resumePending = true;
      void load();
    });
  });
  onDestroy(() => { alive = false; });
</script>

<svelte:head><title>Projects · Cognis</title></svelte:head>

<section class="mx-auto flex w-full max-w-6xl flex-col gap-6 p-4 sm:p-6">
  <div>
    <p class="text-sm uppercase tracking-[0.2em] text-accent">Workspace</p>
    <h1 class="mt-2 text-3xl font-semibold text-strong">Projects</h1>
    <p class="mt-2 max-w-2xl text-sm text-muted">Group conversations, tasks, schedules, source repositories, and preferred workflows under a durable project context.</p>
  </div>

  {#if error}<p class="rounded-xl border border-danger-border bg-danger-subtle p-3 text-sm text-danger">{error}</p>{/if}

  <Card class="p-4">
    <form class="grid gap-3 md:grid-cols-[1fr_2fr_auto]" onsubmit={(event) => { event.preventDefault(); void createProject(); }}>
      <Input bind:value={name} placeholder="Project name" aria-label="Project name" />
      <Input bind:value={description} placeholder="Description" aria-label="Project description" />
      <Button type="submit" disabled={creating || !name.trim()}>{creating ? 'Creating…' : 'Create Project'}</Button>
    </form>
  </Card>

  {#if loading || (loadError && net.hideErrors && projects.length === 0)}
    <p class="text-sm text-muted">Loading projects…</p>
  {:else if projects.length === 0}
    <Card class="p-8 text-center text-muted">No projects yet. Create one to bind workflows and source hints.</Card>
  {:else}
    <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {#each projects as project}
        <div class="group rounded-2xl border border-separator bg-surface/70 p-4 transition hover:border-accent/60 hover:bg-surface">
          <div class="flex items-start gap-3">
            <button type="button" class="shrink-0 cursor-pointer" onclick={() => { profileProject = project; }} aria-label={`Show ${project.name} profile`}>
              <ProjectAvatar name={project.name} avatarUrl={project.avatar_url} icon={project.metadata?.icon} color={project.color} class="h-12 w-12 rounded-xl" />
            </button>
            <div class="min-w-0 flex-1">
              <div class="flex min-w-0 items-start justify-between gap-2">
                <a class="min-w-0 break-words text-lg font-semibold text-strong hover:text-accent-hover lg:truncate lg:group-hover:whitespace-normal lg:group-focus-within:whitespace-normal" href={`/projects/${project.project_id}`} title={project.name}>{project.name}</a>
                <div class="flex shrink-0 gap-1">
                  <a
                    class="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-control-border bg-canvas/70 text-muted transition hover:border-accent/60 hover:text-accent-hover"
                    href={taskBoardProjectUrl(project.project_id)}
                    aria-label={`Open task board filtered for ${project.name}`}
                    title="Open filtered task board"
                  >
                    <ListTodo class="h-4 w-4" aria-hidden="true" />
                  </a>
                  <a
                    class="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-control-border bg-canvas/70 text-muted transition hover:border-accent/60 hover:text-accent-hover"
                    href={scheduleListProjectUrl(project.project_id)}
                    aria-label={`Open schedules filtered for ${project.name}`}
                    title="Open filtered schedules"
                  >
                    <Clock class="h-4 w-4" aria-hidden="true" />
                  </a>
                </div>
              </div>
              <p class="mt-1 line-clamp-2 text-sm text-muted">{project.description || 'No description'}</p>
            </div>
          </div>
          <div class="mt-4 flex gap-2 text-xs text-quiet">
            <span>{project.sources.length} sources</span>
            <span>{project.workflow_ids.length} workflows</span>
            <span>{project.active_schedule_count} schedules</span>
            {#if (project.agents ?? []).length > 0}<span>{(project.agents ?? []).length} agents</span>{/if}
            {#if project.is_shared_with_me}<span class="text-warning">shared with you · {project.caller_role ?? 'member'}</span>{:else if (project.grants ?? []).some((grant) => !grant.revoked_at)}<span class="text-success">shared</span>{/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</section>

{#if profileProject}
  <button class="fixed inset-0 z-40 cursor-default bg-scrim/30" type="button" onclick={() => { profileProject = null; }} aria-label="Close project profile"></button>
  <div class="fixed left-1/2 top-1/2 z-50 w-[min(92vw,24rem)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-control-border bg-elevated p-5 shadow-overlay" role="dialog" aria-modal="true" aria-label={`${profileProject.name} profile`}>
    <div class="flex items-start gap-4">
      <button type="button" class="shrink-0 cursor-pointer disabled:cursor-default" onclick={() => { if (profileProject?.avatar_url) lightboxProject = profileProject; }} aria-label="View avatar full size" disabled={!profileProject.avatar_url}>
        <ProjectAvatar name={profileProject.name} avatarUrl={profileProject.avatar_url} icon={profileProject.metadata?.icon} color={profileProject.color} class="h-20 w-20" />
      </button>
      <div class="min-w-0">
        <p class="break-words text-lg font-semibold text-foreground" title={profileProject.name}>{profileProject.name}</p>
        <p class="mt-1 text-xs uppercase tracking-[0.18em] text-quiet">Project</p>
      </div>
    </div>
    <p class="mt-4 whitespace-pre-wrap text-sm leading-6 text-secondary">{profileProject.description || 'No project description yet.'}</p>
    <div class="mt-5 flex justify-end gap-2">
      <Button variant="secondary" onclick={() => { profileProject = null; }}>Close</Button>
      <Button onclick={() => goto(`/projects/${profileProject?.project_id}`)}>Open project</Button>
    </div>
  </div>
{/if}

{#if lightboxProject?.avatar_url}
  <ImageLightbox src={lightboxProject.avatar_url} alt={`${lightboxProject.name} avatar`} onClose={() => { lightboxProject = null; }} />
{/if}
