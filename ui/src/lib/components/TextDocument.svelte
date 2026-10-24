<script lang="ts">
  import { textFormat } from '$lib/artifact-text';
  import { previewKind } from '$lib/attachments/preview';
  import ArtifactPreviewContent from './ArtifactPreviewContent.svelte';
  import HtmlPreview from './HtmlPreview.svelte';
  import { onMount } from 'svelte';
  import { documentCoordination, type DocumentLease } from '$lib/document-coordination';

  let { text = $bindable(''), mime = 'text/plain', filename = '', editing = false, preview = false, truncated = false, fill = false, label = 'Artifact content', richPayload = null, htmlLease = null }: {
    text?: string; mime?: string; filename?: string; editing?: boolean; preview?: boolean; truncated?: boolean; fill?: boolean; label?: string; richPayload?: unknown;
    htmlLease?: DocumentLease | null;
  } = $props();
  const format = $derived(textFormat(mime, filename));
  const showPreview = $derived(preview || !editing);
  let initialLease = $state<DocumentLease | null>(null);
  onMount(() => {
    // Retain this document's ownership across source/preview toggles.
    try { initialLease = documentCoordination().capture(); } catch { /* Fail closed for HTML only. */ }
  });

  function content(node: HTMLElement, value: { editing: boolean; text: string }) {
    let wasEditing = value.editing;
    const update = (next: typeof value) => {
      if (!next.editing) node.textContent = '';
      else if (!wasEditing || node.textContent === '') node.textContent = next.text;
      wasEditing = next.editing;
    };
    if (value.editing) node.textContent = value.text;
    return { update };
  }
</script>

<div class="min-w-0" class:document-fill={fill}>
  <!-- Keep the same source surface mounted while entering edit mode or preview. -->
  <pre
    use:content={{ editing, text }}
    contenteditable={editing ? 'plaintext-only' : false}
    role={editing ? 'textbox' : undefined}
    aria-label={label}
    aria-multiline={editing ? 'true' : undefined}
    spellcheck="false"
    oninput={(event) => { if (editing) text = event.currentTarget.innerText.replace(/\r\n/g, '\n'); }}
    class="min-h-48 max-h-[65vh] overflow-auto whitespace-pre-wrap break-words p-5 font-mono text-sm leading-6 text-secondary outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
    class:hidden={showPreview}
    class:bg-inset={editing}
  ></pre>
  {#if showPreview}
    {#if format === 'html'}
      {#if htmlLease ?? initialLease}
        <div class="h-[65vh]"><HtmlPreview source={{ text, lease: (htmlLease ?? initialLease)! }} /></div>
      {:else}
        <p role="alert" class="p-5 text-sm text-red-300">This preview is no longer available. Reopen it after signing in.</p>
      {/if}
    {:else}
      <ArtifactPreviewContent kind={previewKind({ filename, mime_type: mime }) ?? 'text'} {filename} {mime} content={text} {truncated} richPayload={editing ? null : richPayload} />
    {/if}
  {/if}
</div>
<style>
  .document-fill { min-height: 100%; display: flex; flex-direction: column; }
  .document-fill > pre { flex: 1; max-height: none; border-radius: 0; }
  .document-fill > div { flex: 1; min-height: 60dvh; }
</style>
