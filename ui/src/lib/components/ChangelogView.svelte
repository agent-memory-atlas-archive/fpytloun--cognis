<script lang="ts">
  import { renderDocsMarkdown } from '$lib/markdown';
  import { releasesBetween, type Release } from '$lib/changelog';

  let {
    releases,
    initialSince = '',
    initialThrough = ''
  }: { releases: Release[]; initialSince?: string; initialThrough?: string } = $props();
  let since = $state('');
  let through = $state('');
  $effect(() => { since = initialSince; });
  $effect(() => { through = initialThrough || releases[0]?.version || ''; });
  let selected = $derived(releasesBetween(releases, since, through));
  let comparisonHref = $derived(`/docs/changelog?${new URLSearchParams({ since, through })}`);
</script>

<section class="mx-auto w-full max-w-4xl space-y-8">
  <header>
    <a href="/docs" class="text-sm text-accent hover:text-accent-hover">Back to docs</a>
    <h1 class="mt-4 text-2xl font-semibold text-strong">What's new</h1>
    <p class="mt-2 text-sm text-muted">Release history and upgrade notes bundled with this Cognis installation.</p>
  </header>

  {#if releases.length}
    <div class="flex flex-wrap items-end gap-4 rounded-xl border border-separator p-4">
      <label class="flex min-w-40 flex-1 flex-col gap-2 text-sm text-secondary">
        Changes after
        <select bind:value={since} class="min-h-11 rounded-lg border border-control-border bg-canvas px-3 text-strong">
          <option value="">Beginning of history</option>
          {#each releases as release}
            <option value={release.version}>{release.version}{release.date === 'Unreleased' ? ' (Unreleased)' : ''}</option>
          {/each}
        </select>
      </label>
      <label class="flex min-w-40 flex-1 flex-col gap-2 text-sm text-secondary">
        Through version
        <select bind:value={through} class="min-h-11 rounded-lg border border-control-border bg-canvas px-3 text-strong">
          {#each releases as release}
            <option value={release.version}>{release.version}{release.date === 'Unreleased' ? ' (Unreleased)' : ''}</option>
          {/each}
        </select>
      </label>
      <a href={comparisonHref} class="inline-flex min-h-11 items-center text-sm text-accent hover:text-accent-hover">
        Link to this comparison
      </a>
    </div>

    {#if !selected.length}
      <p role="status" class="text-sm text-muted">No releases in this range. Choose an earlier starting version and a later ending version.</p>
    {/if}
    {#each selected as release (release.version)}
      <article id={`v${release.version}`} class="min-w-0 border-t border-separator pt-6">
        <header class="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 class="text-xl font-semibold text-strong">
            <a href={`${comparisonHref}#v${release.version}`} class="hover:text-accent-hover">{release.version}</a>
          </h2>
          {#if release.date === 'Unreleased'}
            <span class="text-sm text-warning">Unreleased · preview</span>
          {:else}
            <time datetime={release.date} class="text-sm text-muted">{release.date}</time>
          {/if}
        </header>
        <div class="docs-markdown min-w-0 break-words prose prose-invert max-w-none prose-headings:text-strong prose-p:text-secondary prose-li:text-secondary">
          {@html renderDocsMarkdown(release.markdown)}
        </div>
      </article>
    {/each}
  {:else}
    <p class="text-sm text-muted">No release notes are bundled with this installation.</p>
  {/if}
</section>
