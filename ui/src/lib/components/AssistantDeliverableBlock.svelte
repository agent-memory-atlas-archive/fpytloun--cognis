<script lang="ts">
  import { getContext } from 'svelte';
  import { readable, type Readable } from 'svelte/store';
  import { DELIVERABLE_SHARING_CONTEXT } from '$lib/deliverable-permissions';
  import { api } from '$lib/api/client';
  // Loaded on demand (in parallel with the deliverable fetch) to keep the
  // rich renderer out of the chat startup bundle.
  const richDeliverableModule = import('$lib/components/rich/RichDeliverable.svelte');
  import DeliverableRevisionBar from '$lib/components/DeliverableRevisionBar.svelte';
  import {
    isSupersededRevision,
    loadDeliverableRevision,
    observedLineageRevisions,
    observeLineageRevision,
  } from '$lib/deliverable-revisions';
  import { deliverablePresentation } from '$lib/deliverable-presentation';
  import { privateDeliverableMediaUrl } from '$lib/rich-deliverable';
  import type { AssistantDeliverableTimelineItem as RenderAssistantDeliverableTimelineItem } from '$lib/timeline-render-model';
  import type { AssistantDeliverableTimelineItem } from '$lib/chat-v2/types';
  import type { Deliverable, DeliverableRevisionSummary } from '$lib/types/api';

  import DocumentFavoriteButton from './DocumentFavoriteButton.svelte';
  export let item: AssistantDeliverableTimelineItem | RenderAssistantDeliverableTimelineItem;
  export let loadDeliverable: ((deliverableId: string) => Promise<Deliverable>) | undefined = undefined;
  export let loadRevision: ((deliverableId: string) => Promise<Deliverable>) | undefined = undefined;
  export let showLibraryLink = true;
  export let displayOnly = false;
  export let collapsedByDefault = false;
  export let allowSharing = true;
  export let conversational = false;
  const sharingPermission = getContext<Readable<boolean>>(DELIVERABLE_SHARING_CONTEXT) ?? readable(true);

  // `baseDeliverable` is the revision this card represents; `revisionView` is a
  // revision the user opened from its history, rendered in place.
  let baseDeliverable: Deliverable | null = null;
  let revisionView: Deliverable | null = null;
  let revisionError: string | null = null;
  let revisionGeneration = 0;
  let deliverable: Deliverable | null = null;
  $: deliverable = revisionView ?? baseDeliverable;
  $: supersededCollapsed = !revisionView && isSupersededRevision(baseDeliverable);
  let loading = true;
  let error: string | null = null;
  let accessorConversationId = '';
  let loadGeneration = 0;
  $: deliverableId = 'deliverable_id' in item ? item.deliverable_id : item.deliverableId;

  $: deliverableTitle = deliverable?.title ?? item.title ?? 'Deliverable';
  $: standaloneUrl = deliverable ? `/api/v1/deliverables/${encodeURIComponent(deliverable.deliverable_id)}/view` : '';
  $: pdfUrl = deliverable ? `/api/v1/deliverables/${encodeURIComponent(deliverable.deliverable_id)}/download.pdf` : '';
  $: htmlUrl = deliverable ? `/api/v1/deliverables/${encodeURIComponent(deliverable.deliverable_id)}/download.html` : '';
  $: markdownUrl = deliverable && ['rich', 'markdown'].includes(deliverable.format)
    ? `/api/v1/deliverables/${encodeURIComponent(deliverable.deliverable_id)}/download.md` : '';
  // Every deliverable format renders through RichDeliverable now, giving
  // markdown/plain/html the same unified toolbar (TOC, full-view, share,
  // copy, PDF) and chrome that rich payloads already have -- previously
  // these formats rendered through a separate, far more limited
  // `assistant-deliverable-card` with only "Open standalone page"/
  // "Download PDF"/"Copy share link" actions, no TOC beyond a flat
  // heading list, and no full-view. `rich` payloads pass through as-is;
  // every other format is wrapped as a single block so the existing block
  // renderers do the work: `markdown` already renders full markdown
  // (headings, tables, code with syntax highlighting, links) via
  // MarkdownBlock; `plain` uses the `code` block so literal text is never
  // misinterpreted as markdown; `html` uses the `raw_html` block, a
  // client-only synthetic type (see RawHtmlBlock.svelte) that sanitizes
  // and renders already-HTML content directly instead of running it
  // through the markdown parser, which would otherwise escape it.
  // A single wrapped `markdown` block only ever contributes ONE top-level
  // (level 2) TOC entry -- its own title, taken from the first heading --
  // with every other `#`/`##`/`###` heading nested one level deeper. The
  // shared `isSubstantialDocument()` auto-TOC heuristic gates on
  // `topLevelHeadings >= 4`, which a single block can never satisfy
  // regardless of how many internal headings it has, so a markdown
  // deliverable would silently lose the TOC the old bespoke card used to
  // show. Detect real heading count directly and force `metadata.toc`
  // on/off explicitly (the same threshold the old card used) rather than
  // relying on the generic multi-block heuristic here.
  $: richPayload = deliverable ? deliverablePresentation(deliverable) : null;

  function authenticatedMediaUrlFor(mediaKey: string): string {
    if (!deliverable) return '';
    return privateDeliverableMediaUrl(deliverable.deliverable_id, mediaKey, accessorConversationId);
  }

  function currentConversationId(): string {
    const match = typeof window !== 'undefined' ? window.location.pathname.match(/\/chat\/([^/]+)/) : null;
    return match?.[1] ? decodeURIComponent(match[1]) : '';
  }

  async function createShareLink(options?: import('$lib/components/rich/share-options').ShareLinkOptions): Promise<string> {
    if (!deliverable) throw new Error('Deliverable is not loaded');
    const result = await api.artifactDocuments.publicLink('deliverable', deliverable.deliverable_id, { ...options, mode: options?.mode ?? 'view' });
    return result.url;
  }

  async function loadCurrent(
    id: string,
    loaderOverride: ((deliverableId: string) => Promise<Deliverable>) | undefined,
    previewOnly: boolean,
  ): Promise<void> {
    const generation = ++loadGeneration;
    loading = true;
    error = null;
    if (baseDeliverable?.deliverable_id !== id) baseDeliverable = null;
    revisionView = null;
    revisionError = null;
    accessorConversationId = currentConversationId();
    if (previewOnly && !loaderOverride) {
      loading = false;
      return;
    }
    try {
      const result = await (loaderOverride
        ? loaderOverride(id)
        : api.deliverables.get(id, { accessorConversationId }));
      if (generation === loadGeneration && deliverableId === id) baseDeliverable = result;
    } catch (err) {
      if (generation === loadGeneration && deliverableId === id) {
        error = err instanceof Error ? err.message : 'Failed to load deliverable';
      }
    } finally {
      if (generation === loadGeneration && deliverableId === id) loading = false;
    }
  }

  $: void loadCurrent(deliverableId, loadDeliverable, displayOnly);

  // Publish this card's revision, and refresh lineage facts when a newer
  // revision of the same lineage is rendered after this card loaded.
  $: itemLineageId = 'deliverable_id' in item ? item.lineage_id : item.lineageId;
  $: itemRevision = item.revision;
  $: observeLineageRevision(itemLineageId, itemRevision);
  $: observeLineageRevision(baseDeliverable?.lineage_id, baseDeliverable?.revision);
  $: lineageKey = itemLineageId ?? baseDeliverable?.lineage_id ?? null;
  $: observedLatest = lineageKey ? $observedLineageRevisions[lineageKey] ?? 0 : 0;
  let refreshedForRevision = 0;
  $: if (
    baseDeliverable
    && observedLatest > (baseDeliverable.latest_revision ?? baseDeliverable.revision ?? 1)
    && observedLatest > refreshedForRevision
  ) {
    refreshedForRevision = observedLatest;
    void refreshBase(baseDeliverable.deliverable_id);
  }

  async function refreshBase(id: string): Promise<void> {
    const generation = loadGeneration;
    try {
      const result = await (loadDeliverable
        ? loadDeliverable(id)
        : api.deliverables.get(id, { accessorConversationId }));
      if (generation === loadGeneration && deliverableId === id) baseDeliverable = result;
    } catch {
      // Keep the loaded revision; lineage facts refresh on the next load.
    }
  }

  async function openRevision(revision: DeliverableRevisionSummary): Promise<void> {
    const generation = ++revisionGeneration;
    revisionError = null;
    if (revision.deliverable_id === baseDeliverable?.deliverable_id) {
      revisionView = null;
      return;
    }
    try {
      const result = await (loadRevision
        ? loadRevision(revision.deliverable_id)
        : loadDeliverableRevision(revision, { accessorConversationId }));
      if (generation === revisionGeneration) revisionView = result;
    } catch (err) {
      if (generation === revisionGeneration) {
        revisionError = err instanceof Error ? err.message : 'Could not load revision';
      }
    }
  }
</script>

<div class="assistant-deliverable-wrapper" class:conversational data-deliverable-id={deliverableId} data-collapsed-by-default={collapsedByDefault ? 'true' : undefined}>
  {#if loading && !deliverable}
    <div class="text-sm text-muted">Loading deliverable…</div>
  {:else if displayOnly && !deliverable}
    <div class="rounded-xl border border-control-border bg-surface/60 p-3" data-testid="display-only-deliverable">
      <p class="text-sm font-medium text-foreground">{deliverableTitle}</p>
      {#if item.format}<p class="mt-1 text-xs text-quiet">{item.format} deliverable · preview only</p>{/if}
      {#if item.content && !collapsedByDefault}<p class="mt-2 line-clamp-6 whitespace-pre-wrap text-sm text-secondary">{item.content}</p>{/if}
    </div>
  {:else if error && !deliverable}
    <div class="space-y-2">
      <div class="text-sm font-medium text-danger">Could not load deliverable</div>
      <div class="text-xs text-quiet">{error}</div>
      {#if item.content}
        <div class="rounded-xl border border-control-border bg-surface/60 p-3 text-sm text-foreground">
          {item.content}
        </div>
      {/if}
    </div>
  {:else if deliverable && richPayload}
    {#if showLibraryLink && !displayOnly && !conversational}
      <div class="mb-2 flex justify-end"><a class="inline-flex min-h-9 items-center text-xs text-accent hover:text-accent-hover hover:underline" href={`/library/deliverable/${encodeURIComponent(deliverable.deliverable_id)}`}>Open in Library ↗</a></div>
    {/if}
    {#if !conversational}<DeliverableRevisionBar current={deliverable} anchorId={baseDeliverable?.deliverable_id ?? deliverableId} onSelect={(revision) => void openRevision(revision)} />{/if}
    {#if revisionError}<p class="mb-2 text-xs text-danger">{revisionError}</p>{/if}
    <!-- Remount when the card becomes superseded so it applies the collapsed default. -->
    {#key `${deliverable.deliverable_id}:${supersededCollapsed}`}
    {#await richDeliverableModule then { default: RichDeliverable }}
    <RichDeliverable
      title={deliverableTitle}
      content={deliverable.content}
      payload={richPayload}
      instanceId={deliverable.deliverable_id}
      internalUrl={conversational && (!showLibraryLink || displayOnly) ? '' : `/library/deliverable/${encodeURIComponent(deliverable.deliverable_id)}`}
      mediaUrlFor={authenticatedMediaUrlFor}
      standaloneUrl={standaloneUrl}
      pdfUrl={pdfUrl}
      htmlUrl={htmlUrl}
      markdownUrl={markdownUrl}
      shareLinkCallback={allowSharing && $sharingPermission ? createShareLink : undefined}
      surface="embedded"
      {conversational}
      compact
      collapsedByDefault={collapsedByDefault || supersededCollapsed}
    >
      {#snippet extraActions()}<DocumentFavoriteButton kind="deliverable" id={deliverable.deliverable_id} showLabel={conversational} />{/snippet}
      {#snippet footer()}
        <DeliverableRevisionBar current={deliverable} anchorId={baseDeliverable?.deliverable_id ?? deliverableId} onSelect={(revision) => void openRevision(revision)} />
      {/snippet}
    </RichDeliverable>
    {/await}
    {/key}
  {/if}
</div>

<style>
  .assistant-deliverable-wrapper {
    width: 100%;
    min-width: 0;
    max-width: 100%;
    margin: 0.75rem 0;
    /* RichDeliverable owns all its own document chrome now for every
       format; avoid a nested frame here. */
    padding: 0;
  }
  /* Match ChatMessage's avatar, gap, bubble padding and one-pixel border. */
  .assistant-deliverable-wrapper.conversational { box-sizing: border-box; padding-left: calc(3.25rem + 1px); }
  @media (min-width: 640px) {
    .assistant-deliverable-wrapper.conversational { padding-left: calc(3.75rem + 1px); }
  }
</style>
