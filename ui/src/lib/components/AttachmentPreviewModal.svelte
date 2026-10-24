<script lang="ts">
  import X from 'lucide-svelte/icons/x';
  import { getContext, onMount, tick } from 'svelte';
  import { readable, type Readable } from 'svelte/store';
  import { DELIVERABLE_SHARING_CONTEXT } from '$lib/deliverable-permissions';

  import { portal } from '$lib/actions/portal';
  import { api } from '$lib/api/client';
  import type { AttachmentPreviewKind } from '$lib/attachments/preview';
  import ArtifactPreviewContent from './ArtifactPreviewContent.svelte';
  import AttachmentSaveButton from './AttachmentSaveButton.svelte';
  import { isTopOverlay, registerOverlay } from '$lib/stores/overlays';
  import type { AttachmentRef } from '$lib/types/api';
  import DocumentLinkActions from './rich/DocumentLinkActions.svelte';
  import DocumentFavoriteButton from './DocumentFavoriteButton.svelte';
  import type { ShareLinkOptions } from './rich/share-options';
  import { viewEligible } from '$lib/artifact-text';
  import type { SignedHtmlPreview } from '$lib/attachments/html-preview';

  let {
    attachment,
    kind,
    mediaUrl = null,
    htmlSource = null,
    onClose,
    resolveDownloadUrl,
  }: {
    attachment: AttachmentRef;
    kind: AttachmentPreviewKind;
    mediaUrl?: string | null;
    htmlSource?: SignedHtmlPreview | null;
    onClose: () => void;
    resolveDownloadUrl: () => Promise<string | null>;
  } = $props();

  let panel = $state<HTMLDivElement | null>(null);
  let closeButton = $state<HTMLButtonElement | null>(null);
  let overlayId = $state<string | null>(null);
  let content = $state('');
  let truncated = $state(false);
  let richPayload = $state<unknown>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  const sharingPermission = getContext<Readable<boolean>>(DELIVERABLE_SHARING_CONTEXT) ?? readable(true);
  async function createPublicLink(options: ShareLinkOptions): Promise<string> {
    return (await api.artifactDocuments.publicLink('artifact', attachment.artifact_id, { ...options, mode: options.mode ?? 'download' })).url;
  }

  function handleKeydown(event: KeyboardEvent): void {
    if (!isTopOverlay(overlayId)) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== 'Tab' || !panel) return;
    const elements = Array.from(panel.querySelectorAll<HTMLElement>('button:not([disabled]), [href], [controls], [tabindex]:not([tabindex="-1"])'));
    if (elements.length === 0) return;
    const first = elements[0];
    const last = elements[elements.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  onMount(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overlay = registerOverlay({ kind: 'fullscreen', blocksChrome: true });
    overlayId = overlay.id;
    void tick().then(() => closeButton?.focus());
    if (['text', 'markdown', 'mermaid', 'csv'].includes(kind)) {
      void api.artifacts.textPreview(attachment.artifact_id).then((result) => {
        content = result.content;
        truncated = result.truncated;
        richPayload = result.rich_payload;
      }).catch(() => {
        error = 'The attachment preview could not be loaded.';
      }).finally(() => {
        loading = false;
      });
    } else {
      loading = false;
    }
    return () => {
      overlay.unregister();
      overlayId = null;
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  });
</script>

<svelte:window onkeydown={handleKeydown} />

<div use:portal bind:this={panel} class="app-viewport-overlay app-safe-fullscreen z-[90] isolate overflow-hidden bg-surface text-foreground" role="dialog" aria-modal="true" aria-labelledby="attachment-preview-title" tabindex="-1" data-blocking-overlay>
    <div class="app-safe-fullscreen__toolbar flex min-w-0 items-center justify-between gap-2 border-b border-separator bg-chrome px-2 py-1">
      <div class="min-w-0">
        <h2 id="attachment-preview-title" class="truncate text-lg font-semibold text-foreground">{attachment.filename}</h2>
        <p class="mt-0.5 text-xs text-muted">{attachment.mime_type ?? 'file'}</p>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <AttachmentSaveButton filename={attachment.filename} resolveUrl={resolveDownloadUrl} class="document-icon-action" />
        <DocumentFavoriteButton kind="artifact" id={attachment.artifact_id} />
        <DocumentLinkActions internalUrl={`/library/artifact/${encodeURIComponent(attachment.artifact_id)}`} createLink={$sharingPermission ? createPublicLink : undefined} defaultMode={viewEligible(attachment.mime_type ?? '', attachment.filename) ? 'view' : 'download'} />
        <button bind:this={closeButton} class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg text-foreground hover:bg-surface-hover" onclick={onClose} type="button" title="Close" aria-label="Close preview"><X class="h-5 w-5" /></button>
      </div>
    </div>
    <div class={`app-safe-fullscreen__content min-w-0 ${['html', 'pdf', 'video', 'audio'].includes(kind) ? 'overflow-hidden' : 'overflow-auto p-3'}`}>
      {#if loading}
        <p class="text-sm text-muted">Loading preview…</p>
      {:else if error}
        <p class="text-sm text-danger">{error}</p>
      {:else}
        <ArtifactPreviewContent {kind} filename={attachment.filename} mime={attachment.mime_type} {content} {richPayload} {truncated} {mediaUrl} {htmlSource} />
      {/if}
    </div>
</div>
