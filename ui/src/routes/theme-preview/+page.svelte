<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { userPreferences } from '$lib/stores/userPreferences';
  import { projectAppearance, resolveTheme } from '$lib/theme/appearance';
  import { DEFAULT_THEME_FAMILY, THEME_FAMILIES, normalizeThemeFamily, type ThemeFamily } from '$lib/theme/catalog';
  import Badge from '$lib/components/ui/Badge.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import Card from '$lib/components/ui/Card.svelte';
  import Input from '$lib/components/ui/Input.svelte';
  import AccessibleTabs from '$lib/components/ui/AccessibleTabs.svelte';
  import Sheet from '$lib/components/ui/Sheet.svelte';
  import ActivityStrip from '$lib/components/task-cockpit/ActivityStrip.svelte';

  type Theme = 'light' | 'dark' | 'system';
  let theme = $state<Theme>('system');
  let family = $state<ThemeFamily>(DEFAULT_THEME_FAMILY);
  let systemDark = $state(false);
  let ready = $state(false);
  let tab = $state('overview');
  let message = $state('');
  let decision = $state('');
  let sheetOpen = $state(false);
  const resolved = $derived(resolveTheme(theme, systemDark));
  const tabs = [{ id: 'overview', label: 'Overview' }, { id: 'activity', label: 'Activity', count: 3 }];

  onMount(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    let active = true;
    // Root appearance subscribes during parent mount, after this child mounts.
    // Apply after account preference subscribers or OS listeners finish, without
    // writing either account preferences or their persisted cache.
    const schedulePreview = () => {
      queueMicrotask(() => {
        if (!active) return;
        projectAppearance(family, resolveTheme(theme, media.matches));
      });
    };
    const stopPreferences = userPreferences.subscribe(schedulePreview);
    const query = new URLSearchParams(window.location.search);
    const queryTheme = query.get('theme');
    family = normalizeThemeFamily(query.get('family'));
    if (queryTheme === 'light' || queryTheme === 'dark' || queryTheme === 'system') theme = queryTheme;
    systemDark = media.matches;
    ready = true;
    const updateSystem = () => {
      systemDark = media.matches;
      schedulePreview();
    };
    media.addEventListener('change', updateSystem);
    return () => {
      active = false;
      stopPreferences();
      media.removeEventListener('change', updateSystem);
      const account = get(userPreferences).display;
      projectAppearance(account.theme_family, resolveTheme(account.theme, media.matches));
    };
  });

  $effect(() => {
    if (!ready) return;
    // This isolated fixture never writes the authenticated user's preference.
    projectAppearance(family, resolved);
  });
</script>

<svelte:head><title>Theme preview · Cognis</title></svelte:head>

<main class="min-h-screen bg-canvas text-foreground" data-testid="theme-preview" data-theme={resolved}>
  <header class="border-b border-separator bg-chrome material-chrome">
    <div class="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-5 py-5">
      <div>
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-accent">Cognis workspace</p>
        <h1 class="mt-1 text-2xl font-semibold">Your work, in focus</h1>
        <p class="mt-1 text-sm text-secondary">Interactive theme fixture · local sample content only</p>
      </div>
      <label class="space-y-1 text-sm">
        <span class="block text-secondary">Family</span>
        <select bind:value={family} class="min-h-10 rounded-xl border border-control-border bg-surface px-3 text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          {#each THEME_FAMILIES as item}
            <option value={item.id}>{item.name}</option>
          {/each}
        </select>
      </label>
      <label class="space-y-1 text-sm">
        <span class="block text-secondary">Appearance</span>
        <select bind:value={theme} class="min-h-10 rounded-xl border border-control-border bg-surface px-3 text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          <option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option>
        </select>
      </label>
    </div>
  </header>

  <div class="mx-auto max-w-6xl space-y-6 px-5 py-6">
    <AccessibleTabs {tabs} activeId={tab} onChange={(id) => { tab = id; }} idPrefix="theme-preview" ariaLabel="Workspace sections" />
    <div id={`theme-preview-panel-${tab}`} role="tabpanel" tabindex="0" aria-label={tab === 'overview' ? 'Overview' : 'Activity'} class="grid gap-5 lg:grid-cols-[1.2fr_1fr]">
      <div class="space-y-5">
        <Card class="p-5">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div><h2 class="text-lg font-semibold">Release readiness</h2><p class="mt-1 text-sm text-secondary">Workspace overview</p></div>
            <Badge class="border-success-border bg-success-subtle text-success">On track</Badge>
          </div>
          <div class="mt-5 grid grid-cols-3 gap-3">
            {#each [{ count: '4', label: 'Active tasks' }, { count: '2', label: 'Agents online' }, { count: '1', label: 'Needs review' }] as metric}
              <div class="rounded-xl bg-inset p-3"><p class="text-2xl font-semibold">{metric.count}</p><p class="mt-1 text-xs text-secondary">{metric.label}</p></div>
            {/each}
          </div>
          <div class="mt-5 space-y-3 divide-y divide-separator">
            <div class="flex items-center justify-between gap-3 pt-3"><span class="text-sm">Prepare release notes</span><Badge class="border-success-border bg-success-subtle text-success">Complete</Badge></div>
            <div class="flex items-center justify-between gap-3 pt-3"><span class="text-sm">Verify deployment plan</span><Badge class="border-warning-border bg-warning-subtle text-warning">Approval</Badge></div>
            <div class="flex items-center justify-between gap-3 pt-3"><span class="text-sm">Publish release</span><Badge>Queued</Badge></div>
          </div>
          <div class="mt-5 flex flex-wrap gap-2"><Button onclick={() => { sheetOpen = true; }}>Review task</Button><Button variant="secondary">View workflow</Button><Button disabled>Publish</Button></div>
        </Card>
        <Card class="overflow-hidden">
          <div class="border-b border-separator bg-chrome px-5 py-3"><h2 class="font-semibold">Agent conversation</h2></div>
          <div class="space-y-4 p-5">
            <p class="ml-8 rounded-2xl bg-accent px-4 py-3 text-sm text-on-accent">Check the release plan and summarize anything that needs my attention.</p>
            <div class="mr-6 rounded-2xl border border-separator bg-inset px-4 py-3 text-sm leading-6">
              <p class="font-semibold">LaForge</p><p class="mt-1 text-secondary">The checks passed. The deployment plan is ready for review; publishing still requires your approval.</p>
              <a class="mt-2 inline-block text-accent hover:text-accent-hover" href="#approval">Review approval request →</a>
            </div>
            <ActivityStrip label="Validation complete" stepName="Review deployment" />
            <form class="flex gap-2" onsubmit={(event) => { event.preventDefault(); if (message.trim()) { decision = 'Message saved locally for this preview.'; message = ''; } }}>
              <Input aria-label="Message agent" placeholder="Message your agent…" bind:value={message} />
              <Button type="submit">Send</Button>
            </form>
          </div>
        </Card>
      </div>
      <div class="space-y-5">
        <Card class="p-5" >
          <div id="approval" class="space-y-4">
            <Badge class="border-warning-border bg-warning-subtle text-warning">Action required</Badge>
            <h2 class="text-lg font-semibold">Approve deployment plan</h2>
            <p class="text-sm leading-6 text-secondary">Review the planned change before the agent continues. No external action is performed in this preview.</p>
            <div class="rounded-xl border border-info-border bg-info-subtle p-4 text-sm text-info">The release updates the application UI. Existing data and permissions are unchanged.</div>
            <label class="block space-y-2 text-sm"><span>Review note</span><Input placeholder="Optional feedback" /></label>
            <div class="flex flex-wrap gap-2"><Button onclick={() => { decision = 'Approved locally. No deployment was started.'; }}>Approve</Button><Button variant="danger" onclick={() => { decision = 'Denied locally. The agent remains paused.'; }}>Deny</Button><Button variant="ghost" onclick={() => { decision = 'Request dismissed locally.'; }}>Dismiss</Button></div>
            {#if decision}<p class="text-sm text-secondary" role="status">{decision}</p>{/if}
          </div>
        </Card>
        <Card class="space-y-3 p-5">
          <h2 class="font-semibold">Runtime health</h2>
          <p class="rounded-xl border border-success-border bg-success-subtle p-3 text-sm text-success">Executor connected · all services healthy</p>
          <p class="rounded-xl border border-warning-border bg-warning-subtle p-3 text-sm text-warning">One scheduled task needs review</p>
          <p class="rounded-xl border border-danger-border bg-danger-subtle p-3 text-sm text-danger">Previous publish attempt was denied</p>
          <p class="text-xs text-muted">Updated just now · sample status</p>
        </Card>
      </div>
    </div>
  </div>
</main>

{#if sheetOpen}
  <Sheet open={sheetOpen} label="Deployment review" side="right" onClose={() => { sheetOpen = false; }}>
    {#snippet header()}<h2 class="text-lg font-semibold text-foreground">Deployment review</h2>{/snippet}
    <div class="space-y-4 text-secondary"><p>Validation passed. Review the plan before publishing.</p><Button onclick={() => { sheetOpen = false; }}>Done</Button></div>
  </Sheet>
{/if}
