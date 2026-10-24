<script lang="ts">
  import { mountHtmlPreview, type HtmlPreviewSource } from '$lib/attachments/html-preview';

  let { source }: { source: HtmlPreviewSource } = $props();
  let error = $state<string | null>(null);

  function preview(node: HTMLElement, value: HtmlPreviewSource) {
    let dispose = () => {};
    function update(next: HtmlPreviewSource) {
      dispose();
      node.replaceChildren();
      dispose = mountHtmlPreview(node, next, next.lease, (message) => { error = message; });
    }
    update(value);
    return { update, destroy: () => dispose() };
  }
</script>

{#if error}<p role="alert" class="p-5 text-sm text-red-300">{error}</p>{/if}
{#if error === null}<p role="status" class="p-4 text-sm text-slate-400">Loading HTML preview…</p>{/if}
<div use:preview={source} class="h-full min-h-96 min-w-0"></div>
