<script lang="ts">
  import { page } from '$app/stores';
  import { loadEmbeddedDoc } from '$lib/docs';
  import { getDocMeta, getRelatedDocsMeta } from '$lib/docs-registry';
  import { renderDocsMarkdown } from '$lib/markdown';
  import Card from '$lib/components/ui/Card.svelte';
  import type { EmbeddedDoc } from '$lib/docs';

  let slug = $derived($page.params.slug ?? '');
  let docMeta = $derived(getDocMeta(slug));
  let doc = $state<EmbeddedDoc | null>(null);
  let loading = $state(true);
  let html = $state('');
  let relatedDocs = $derived(docMeta ? getRelatedDocsMeta(docMeta) : []);
  let loadSeq = 0;

  async function loadCurrentDoc(): Promise<void> {
    const currentSeq = ++loadSeq;
    loading = true;
    const loaded = await loadEmbeddedDoc(slug);
    if (currentSeq !== loadSeq) return;
    doc = loaded;
    html = loaded ? renderDocsMarkdown(loaded.content) : '';
    loading = false;
  }

  $effect(() => {
    void slug;
    void loadCurrentDoc();
  });
</script>

<svelte:head>
  <title>{docMeta ? `${docMeta.title} · Docs · Cognis` : 'Doc Not Found · Docs · Cognis'}</title>
</svelte:head>

{#if docMeta}
  <section class="space-y-6">
    <Card class="p-4 sm:p-6">
      <a class="text-sm text-accent" href="/docs">Back to docs</a>
      <p class="mt-4 text-sm uppercase tracking-[0.25em] text-muted">Docs</p>
      <h1 class="mt-2 text-2xl font-semibold text-strong">{docMeta.title}</h1>
      <p class="mt-3 max-w-3xl text-sm leading-6 text-muted">{docMeta.description}</p>
    </Card>

    <Card class="p-4 sm:p-6">
      {#if loading}
        <p class="text-sm text-muted">Loading guide…</p>
      {:else}
        <div class="docs-markdown min-w-0 max-w-full overflow-x-hidden break-words prose prose-invert max-w-none prose-headings:text-strong prose-p:text-secondary prose-strong:text-strong prose-li:text-secondary prose-code:text-accent prose-code:before:content-none prose-code:after:content-none prose-pre:border prose-pre:border-separator prose-pre:bg-canvas/80 prose-table:text-foreground">{@html html}</div>
      {/if}
    </Card>

    {#if relatedDocs.length > 0}
      <Card class="p-4 sm:p-6">
        <p class="text-xs uppercase tracking-[0.25em] text-muted">Related guides</p>
        <div class="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {#each relatedDocs as related}
            <a class="rounded-2xl border border-separator bg-canvas/70 px-4 py-4 transition hover:border-accent/50 hover:bg-canvas/90" href={`/docs/${related.slug}`}>
              <p class="font-medium text-strong">{related.title}</p>
              <p class="mt-2 text-sm leading-6 text-muted">{related.description}</p>
            </a>
          {/each}
        </div>
      </Card>
    {/if}
  </section>
{:else}
  <Card class="p-4 sm:p-6">
    <p class="text-sm uppercase tracking-[0.25em] text-muted">Docs</p>
    <h1 class="mt-2 text-2xl font-semibold text-strong">Document not found</h1>
    <p class="mt-3 max-w-2xl text-sm leading-6 text-muted">
      The requested guide is not part of the bundled Cognis documentation set.
    </p>
    <a class="mt-4 inline-flex text-sm text-accent" href="/docs">Open the docs hub</a>
  </Card>
{/if}
