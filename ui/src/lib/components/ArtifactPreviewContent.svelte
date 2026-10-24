<script lang="ts">
  import { loadHighlighter } from '$lib/syntax/lazy-highlight';
  import { highlightJson, looksLikeJson, prettyPrintJson } from '$lib/syntax/json';
  import { textFormat } from '$lib/artifact-text';
  import { previewLanguage, type AttachmentPreviewKind } from '$lib/attachments/preview';
  import RichDeliverable from './rich/RichDeliverable.svelte';
  import PdfAttachmentViewer from './PdfAttachmentViewer.svelte';
  import HtmlPreview from './HtmlPreview.svelte';
  import type { SignedHtmlPreview } from '$lib/attachments/html-preview';

  let { kind, filename, mime = '', content = '', richPayload = null, truncated = false, mediaUrl = null, htmlSource = null }: {
    kind: AttachmentPreviewKind | 'image' | null; filename: string; mime?: string;
    content?: string; richPayload?: unknown; truncated?: boolean; mediaUrl?: string | null;
    htmlSource?: SignedHtmlPreview | null;
  } = $props();
  let hljs = $state<Awaited<ReturnType<typeof loadHighlighter>> | null>(null);
  $effect(() => {
    if (kind !== 'text') return;
    let cancelled = false;
    void loadHighlighter().then(value => { if (!cancelled) hljs = value; });
    return () => { cancelled = true; };
  });
  const highlighted = $derived.by(() => {
    if (!truncated && textFormat(mime, filename) === 'json' && looksLikeJson(content)) {
      return highlightJson(prettyPrintJson(content));
    }
    const language = previewLanguage(filename, mime);
    try {
      if (hljs && language && hljs.getLanguage(language)) return hljs.highlight(content, { language, ignoreIllegals: true }).value;
    } catch { /* Invalid source remains readable as escaped text. */ }
    return content.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
  });
  const payload = $derived(
    ['markdown', 'mermaid', 'csv'].includes(kind ?? '')
      ? richPayload ?? (kind === 'markdown'
        ? { blocks: [{ type: 'markdown', content }] }
        : null)
      : null,
  );
</script>

{#if kind === 'image' && mediaUrl}
  <img src={mediaUrl} alt={filename || 'Artifact'} class="mx-auto max-h-full max-w-full object-contain p-4" />
{:else if kind === 'pdf' && mediaUrl}
  <PdfAttachmentViewer url={mediaUrl} />
{:else if kind === 'html' && htmlSource}
  <HtmlPreview source={htmlSource} />
{:else if kind === 'video' && mediaUrl}
  <!-- svelte-ignore a11y_media_has_caption: previews cannot synthesize a caption track -->
  <video class="h-full w-full bg-black object-contain" src={mediaUrl} controls playsinline></video>
{:else if kind === 'audio' && mediaUrl}
  <div class="flex h-full items-center justify-center p-3"><audio class="w-full max-w-xl" src={mediaUrl} controls></audio></div>
{:else if ['html', 'pdf', 'video', 'audio'].includes(kind ?? '')}
  <p class="p-4 text-sm text-danger">The document preview could not be loaded.</p>
{:else if payload}
  {#if truncated}<p class="p-3 text-xs text-warning">Preview is truncated to safe display limits. Download the complete file.</p>{/if}
  <RichDeliverable {content} {payload} surface="embedded" hosted title={filename} />
{:else if kind}
  {#if truncated}<p class="p-3 text-xs text-warning">Preview limited to the first 512 KB. Download the complete file.</p>{/if}
  <pre class="min-h-full overflow-x-auto whitespace-pre-wrap break-words bg-inset p-5 text-sm leading-6 text-secondary"><code class="hljs">{@html highlighted}</code></pre>
{:else}
  <p class="p-8 text-sm text-quiet">No inline preview for this format. Use Download to open it.</p>
{/if}
