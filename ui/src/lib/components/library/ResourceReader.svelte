<script lang="ts">
  import { resolveHtmlPreviewUrl, type SignedHtmlPreview } from '$lib/attachments/html-preview';
  import { documentCoordination, type DocumentLease } from '$lib/document-coordination';
  import { onMount } from 'svelte';
  import { beforeNavigate } from '$app/navigation';
  import { api } from '$lib/api/client';
  import { auth } from '$lib/stores/auth';
  import Button from '$lib/components/ui/Button.svelte';
  import AttachmentSaveButton from '$lib/components/AttachmentSaveButton.svelte';
  import DocumentLinkActions from '$lib/components/rich/DocumentLinkActions.svelte';
  import DocumentFavoriteButton from '$lib/components/DocumentFavoriteButton.svelte';
  import DownloadMenu from '$lib/components/rich/DownloadMenu.svelte';
  import TextDocument from '$lib/components/TextDocument.svelte';
  import ArtifactPreviewContent from '$lib/components/ArtifactPreviewContent.svelte';
  import { previewKind } from '$lib/attachments/preview';
  import DocumentAgents from './DocumentAgents.svelte';
  import Eye from 'lucide-svelte/icons/eye';
  import Pencil from 'lucide-svelte/icons/pencil';
  import Info from 'lucide-svelte/icons/info';
  import X from 'lucide-svelte/icons/x';
  import { syntaxError, viewEligible } from '$lib/artifact-text';
  import { deliverablePresentation } from '$lib/deliverable-presentation';
  import { formatLabel, libraryHref, originLabel, type LibraryItem } from '$lib/library';
  import type { Deliverable } from '$lib/types/api';
  import type { ShareLinkOptions } from '$lib/components/rich/share-options';
  import '$lib/components/rich/document-actions.css';

  let { item, onRevision, onDirtyChange, onBusyChange, onClose }: {
    item: LibraryItem; onRevision?: (item: LibraryItem) => void;
    onDirtyChange?: (dirty: boolean) => void; onBusyChange?: (busy: boolean) => void;
    onClose?: () => void;
  } = $props();
  let mediaUrl = $state('');
  let htmlSource = $state<SignedHtmlPreview | null>(null);
  let editHtmlLease = $state<DocumentLease | null>(null);
  let text = $state('');
  let truncated = $state(false);
  let richPayload = $state<unknown>(null);
  let error = $state('');
  let loading = $state(false);
  let revisions = $state<{ id: string; revision: number; is_latest: boolean }[]>([]);
  let deliverable = $state<Deliverable | null>(null);
  let RichView = $state<typeof import('$lib/components/rich/RichDeliverable.svelte')['default'] | null>(null);
  let editing = $state(false);
  let preview = $state(false);
  let displayed = $state('');
  let original = $state('');
  let filename = $state('');
  let busy = $state(false);
  let detailsOpen = $state(false);
  const isImage = $derived(item.format.startsWith('image/'));
  const kind = $derived(previewKind({ filename: item.title ?? '', mime_type: item.format }));
  const isHTML = $derived(kind === 'html');
  const isText = $derived(['text', 'markdown', 'csv', 'mermaid'].includes(kind ?? ''));
  const canMutate = $derived(!item.is_readonly && $auth.user?.role !== 'viewer');
  const canEdit = $derived(canMutate && item.kind === 'artifact' && (item.size_bytes == null || item.size_bytes <= 1024 * 1024) && (isText || isHTML));
  const dirty = $derived(editing && (displayed !== original || filename !== item.title));
  const validation = $derived(editing ? syntaxError(displayed, item.format, filename) : '');
  const downloadBase = $derived(`/api/v1/deliverables/${encodeURIComponent(item.id)}`);
  $effect(() => { onDirtyChange?.(dirty); onBusyChange?.(busy); });
  $effect(() => { if (!editing) displayed = text; });
  beforeNavigate((navigation) => {
    if (busy || (dirty && !confirm('Discard unsaved artifact changes?'))) navigation.cancel();
  });
  onMount(() => { detailsOpen = matchMedia('(min-width: 1024px)').matches; });

  async function startEdit() {
    busy = true; error = '';
    try {
      const lease = isHTML ? documentCoordination().capture() : null;
      const result = await api.artifactDocuments.source(item.id);
      await lease?.validate();
      editHtmlLease = lease;
      displayed = result.content; original = result.content; filename = result.filename;
      editing = true; preview = false;
    } catch (caught) { error = caught instanceof Error ? caught.message : 'Could not load editable source.'; }
    finally { busy = false; }
  }
  async function saveEdit() {
    if (validation) return;
    busy = true; error = '';
    try {
      const created = await api.artifactDocuments.revise(item.id, { filename, mime_type: item.format, content: displayed });
      editing = false; preview = false; busy = false;
      if (onRevision) onRevision(created); else item = created;
    } catch (caught) { error = caught instanceof Error ? caught.message : 'Could not save. Your draft is preserved.'; }
    finally { busy = false; }
  }
  async function selectRevision(id: string) {
    if (!id || id === item.id || busy) return;
    busy = true; error = '';
    try {
      const selected = await api.library.item(item.kind, id);
      if (onRevision) onRevision(selected); else item = selected;
    } catch (caught) { error = caught instanceof Error ? caught.message : 'Could not open that revision.'; }
    finally { busy = false; }
  }
  async function createPublicLink(options: ShareLinkOptions): Promise<string> {
    return (await api.artifactDocuments.publicLink(item.kind, item.id, { ...options, mode: options.mode ?? 'view' })).url;
  }

  $effect(() => {
    const current = item;
    const controller = new AbortController();
    let cancelled = false;
    error = ''; mediaUrl = ''; htmlSource = null; text = ''; richPayload = null; deliverable = null; revisions = [];
    editing = false; preview = false; loading = true;
    if (current.kind === 'deliverable') {
      void Promise.all([
        api.library.content(current.id), api.deliverables.revisions(current.id).catch(() => {
          if (!cancelled) error = 'Revision history is unavailable. You can still read this document.';
          return { revisions: [] };
        }),
        import('$lib/components/rich/RichDeliverable.svelte'),
      ]).then(([value, history, module]) => {
        if (cancelled) return;
        deliverable = value; RichView = module.default;
        revisions = history.revisions.map(r => ({ id: r.deliverable_id, revision: r.revision, is_latest: r.is_latest }));
      }).catch(caught => { if (!cancelled) error = caught instanceof Error ? caught.message : 'Could not load deliverable.'; })
        .finally(() => { if (!cancelled) loading = false; });
    } else {
      const currentKind = previewKind({ filename: current.title ?? '', mime_type: current.format });
      const textual = ['text', 'markdown', 'csv', 'mermaid'].includes(currentKind ?? '');
      void Promise.all([
        currentKind === 'html'
          ? resolveHtmlPreviewUrl(current.id, controller.signal)
          : api.artifacts.signedUrl(current.id, 3600, currentKind === 'pdf' ? 'view' : 'download'),
        textual ? api.artifacts.textPreview(current.id) : Promise.resolve(null),
        api.artifacts.revisions(current.id).catch(() => {
          if (!cancelled) error = 'Revision history is unavailable. You can still read this document.';
          return { revisions: [] };
        }),
      ]).then(([url, content, history]) => {
        if (cancelled) return;
        htmlSource = 'lease' in url ? url as SignedHtmlPreview : null;
        mediaUrl = url.url; text = content?.content ?? ''; truncated = content?.truncated ?? false;
        richPayload = content?.rich_payload ?? null;
        revisions = history.revisions.map(r => ({ id: r.artifact_id, revision: r.revision, is_latest: r.is_latest }));
      }).catch(caught => { if (!cancelled) error = caught instanceof Error ? caught.message : 'Could not load file.'; })
        .finally(() => { if (!cancelled) loading = false; });
    }
    return () => { cancelled = true; controller.abort(); };
  });
</script>

<svelte:window onbeforeunload={(event) => { if (dirty || busy) { event.preventDefault(); event.returnValue = ''; } }} />

<section class="resource-reader flex h-full min-h-0 flex-col bg-canvas" data-testid="resource-reader">
  <header class="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-separator px-4 py-3 sm:px-5">
    <div class="min-w-0 flex-1 basis-40">
      <h2 class="truncate text-sm font-semibold text-foreground" title={item.title ?? ''}>{item.title || 'Untitled document'}</h2>
      <p class="mt-0.5 text-xs text-quiet">{formatLabel(item.format)} · Revision {item.revision ?? 1}{editing ? ' · Editing' : ''}</p>
    </div>
    <nav class="flex max-w-full flex-wrap items-center gap-1.5" aria-label="Document actions">
      {#if editing}
        <button class="document-icon-action" aria-label="Preview artifact" title={preview ? 'Return to source' : 'Preview artifact'} aria-pressed={preview} onclick={() => { preview = !preview; }} disabled={busy}><Eye size={18} /></button>
        <Button variant="ghost" onclick={() => { editing = false; preview = false; }} disabled={busy}>Cancel</Button>
        <Button onclick={saveEdit} disabled={busy || !!validation || !filename.trim() || !dirty}>{busy ? 'Saving…' : 'Save changes'}</Button>
      {:else}
        {#if revisions.length > 1}
          <select aria-label="Revision history" value={item.id} onchange={(event) => void selectRevision(event.currentTarget.value)} disabled={busy} class="h-10 max-w-36 rounded-lg border border-separator bg-surface px-2 text-xs text-secondary">
            {#each revisions as revision (revision.id)}<option value={revision.id}>Revision {revision.revision}{revision.is_latest ? ' · Latest' : ''}</option>{/each}
          </select>
        {/if}
        {#if canEdit}<button class="document-icon-action" aria-label="Edit" title="Edit" disabled={busy || loading} onclick={startEdit}><Pencil size={18} /></button>{/if}
        {#if item.kind === 'deliverable'}
          <DownloadMenu pdfUrl={`${downloadBase}/download.pdf`} htmlUrl={`${downloadBase}/download.html`} markdownUrl={['rich', 'markdown'].includes(item.format) ? `${downloadBase}/download.md` : ''} />
        {:else}
          <AttachmentSaveButton filename={item.title || 'artifact'} resolveUrl={async () => (await api.artifacts.signedUrl(item.id, 3600, 'download')).url} class="document-icon-action" />
        {/if}
        <DocumentFavoriteButton kind={item.kind} id={item.id} initial={item} />
        <DocumentLinkActions internalUrl={libraryHref(item)} createLink={canMutate ? createPublicLink : undefined} defaultMode={item.kind === 'deliverable' || viewEligible(item.format, item.title ?? '') ? 'view' : 'download'} />
      {/if}
      <button class="document-icon-action" aria-label={detailsOpen ? 'Hide details' : 'Show details'} title="Details" aria-pressed={detailsOpen} onclick={() => { detailsOpen = !detailsOpen; }}><Info size={18} /></button>
      {#if onClose}<button class="document-icon-action" aria-label="Close resource" title="Close" disabled={busy} onclick={onClose}><X size={18} /></button>{/if}
    </nav>
  </header>
  {#if editing}
    <div class="shrink-0 border-b border-separator px-4 py-3">
      <label class="flex items-center gap-3 text-xs text-muted">File name
        <input aria-label="Artifact name" bind:value={filename} disabled={busy} class="min-h-10 min-w-0 flex-1 rounded-lg border border-control-border bg-surface px-3 text-sm text-foreground focus:border-accent focus:outline-none" />
      </label>
    </div>
  {/if}
  {#if validation || error}<p role="alert" class="shrink-0 border-b border-separator px-5 py-3 text-sm text-danger">{validation || error}</p>{/if}
  <div class="relative flex min-h-0 flex-1">
    <main class="min-h-0 min-w-0 flex-1 overflow-auto" aria-label="Document preview">
      {#if loading}<p role="status" class="p-6 text-sm text-muted">Loading document…</p>
      {:else if item.kind === 'deliverable' && deliverable && RichView}
        <RichView payload={deliverablePresentation(deliverable)} content={deliverable.content ?? ''} title={deliverable.title ?? ''} instanceId={deliverable.deliverable_id} surface="embedded" hosted />
      {:else if item.kind === 'artifact'}
        {#if editing || (isText && !isHTML)}
          <TextDocument bind:text={displayed} mime={item.format} filename={editing ? filename : item.title ?? ''} {editing} {preview} {truncated} {richPayload} htmlLease={editHtmlLease} fill />
        {:else}
          <ArtifactPreviewContent kind={isImage ? 'image' : kind} filename={item.title ?? ''} mime={item.format} {mediaUrl} {htmlSource} />
        {/if}
      {/if}
    </main>
    {#if detailsOpen}
      <aside class="absolute inset-y-0 right-0 z-10 w-64 shrink-0 space-y-6 overflow-auto border-l border-separator bg-canvas p-5 shadow-xl lg:static lg:shadow-none" aria-label="Document details">
        <div class="flex items-center justify-between"><h3 class="text-sm font-medium text-foreground">Details</h3>
          <Button variant="ghost" size="icon" aria-label="Close details" onclick={() => { detailsOpen = false; }} class="lg:hidden"><X size={16} /></Button>
        </div>
        <DocumentAgents {item} canManage={canMutate} />
        <dl class="space-y-4 text-xs">
          <div><dt class="text-quiet">Source</dt><dd class="mt-1 text-secondary">{originLabel(item.origin)}</dd></div>
          <div><dt class="text-quiet">Project</dt><dd class="mt-1 text-secondary">{#if item.project_id}<a class="text-accent hover:underline" href={`/projects/${encodeURIComponent(item.project_id)}`}>{item.project_name || 'Project'}</a>{:else}No project{/if}</dd></div>
          <div><dt class="text-quiet">Conversation</dt><dd class="mt-1 break-words text-secondary">{#if item.conversation_id}<a class="text-accent hover:underline" href={`/chat/${encodeURIComponent(item.conversation_id)}`}>{item.conversation_title || 'Open conversation'}</a>{:else}Source unavailable{/if}</dd></div>
          {#if item.task_id}<div><dt class="text-quiet">Task</dt><dd class="mt-1 break-words"><a class="text-accent hover:underline" href={`/tasks?task_id=${encodeURIComponent(item.task_id)}`}>{item.task_title || 'Open task'}</a></dd></div>{/if}
          <div><dt class="text-quiet">Format</dt><dd class="mt-1 text-secondary">{formatLabel(item.format)}{#if item.size_bytes != null} · {new Intl.NumberFormat(undefined, { notation: 'compact' }).format(item.size_bytes)} B{/if}</dd></div>
          <div><dt class="text-quiet">Created</dt><dd class="mt-1 text-secondary">{new Date(item.created_at).toLocaleString()}</dd></div>
          <div><dt class="text-quiet">Updated</dt><dd class="mt-1 text-secondary">{new Date(item.updated_at).toLocaleString()}</dd></div>
        </dl>
      </aside>
    {/if}
  </div>
</section>
