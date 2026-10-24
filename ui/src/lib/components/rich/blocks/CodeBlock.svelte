<script lang="ts">
  import { blockText, blockTitle, type RichBlock } from '$lib/rich-deliverable';
  import { HIGHLIGHT_ATTR } from '$lib/syntax/lazy-highlight';
  import { prettyPrintJson } from '$lib/syntax/json';

  export let block: RichBlock;

  $: language = blockText(block, 'language') || blockText(block, 'lang');
  $: source = language.toLowerCase() === 'json' ? prettyPrintJson(blockText(block)) : blockText(block);
  // Plain text first; the document-level lazy highlighter (lazy-highlight.ts)
  // highlights it in place when visible, loading highlight.js on demand.
  $: highlightAttrs = language ? { [HIGHLIGHT_ATTR]: language.toLowerCase() } : {};
</script>

<section class="rich-code-card" data-rich-block-type="code">
  {#if blockTitle(block)}<h4>{blockTitle(block)}</h4>{/if}
  {#if language}<p class="rich-code-language">{language}</p>{/if}
  {#key `${language}\u0000${source}`}
    <pre class="rich-code"><code {...highlightAttrs}>{source}</code></pre>
  {/key}
</section>
