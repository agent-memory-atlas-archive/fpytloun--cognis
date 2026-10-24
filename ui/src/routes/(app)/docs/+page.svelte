<script lang="ts">
  import { onMount } from 'svelte';
  import { renderDocsMarkdown } from '$lib/markdown';
  import Card from '$lib/components/ui/Card.svelte';
  import { loadDocsOverviewContent } from '$lib/docs';
  import { getCategoryLabel, getDocsByCategoryMeta } from '$lib/docs-registry';

  const groups = getDocsByCategoryMeta();
  let overviewHtml = $state('');
  let overviewLoading = $state(true);

  onMount(() => {
    void loadDocsOverviewContent()
      .then((overview) => {
        overviewHtml = renderDocsMarkdown(overview.content);
      })
      .finally(() => {
        overviewLoading = false;
      });
  });
</script>

<svelte:head>
  <title>Docs · Cognis</title>
</svelte:head>

<section class="space-y-6">
  <Card class="p-4 sm:p-6">
    <p class="text-sm uppercase tracking-[0.25em] text-accent">Docs</p>
    <h1 class="mt-2 text-2xl font-semibold text-strong">Embedded user guides</h1>
    <p class="mt-3 max-w-3xl text-sm leading-6 text-muted">
      Read setup and workspace guidance directly inside Cognis. These pages are bundled with the UI, so they stay available in self-hosted deployments without opening GitHub.
    </p>
    <a href="/docs/changelog" class="mt-4 inline-flex min-h-11 items-center text-sm text-accent hover:text-accent-hover">What's new · Release history and version comparison</a>
  </Card>

  <Card class="p-4 sm:p-6">
    {#if overviewLoading}
      <p class="text-sm text-muted">Loading documentation overview…</p>
    {:else}
      <div class="docs-markdown min-w-0 max-w-full overflow-x-hidden break-words prose prose-invert max-w-none prose-headings:text-strong prose-p:text-secondary prose-strong:text-strong prose-li:text-secondary prose-code:text-accent prose-code:before:content-none prose-code:after:content-none prose-pre:border prose-pre:border-separator prose-pre:bg-canvas/80 prose-table:text-foreground">{@html overviewHtml}</div>
    {/if}
  </Card>

  {#each groups as group}
    <section class="space-y-4">
      <div>
        <p class="text-xs uppercase tracking-[0.25em] text-muted">{getCategoryLabel(group.category)}</p>
      </div>
      <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {#each group.docs as doc}
          <a class="rounded-2xl border border-separator bg-canvas/70 p-5 transition hover:border-accent/50 hover:bg-canvas/90" href={`/docs/${doc.slug}`}>
            <p class="font-medium text-strong">{doc.title}</p>
            <p class="mt-3 text-sm leading-6 text-muted">{doc.description}</p>
          </a>
        {/each}
      </div>
    </section>
  {/each}
</section>
