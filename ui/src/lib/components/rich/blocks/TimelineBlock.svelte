<script lang="ts">
  import { renderInlineMarkdown } from '$lib/markdown';
  import { blockTitle, type RichBlock } from '$lib/rich-deliverable';
  import { listBackedItems } from '../block-helpers';

  export let block: RichBlock;
  export let type = 'timeline';

  $: items = listBackedItems(block);
  function itemTitle(item: Record<string, unknown>, index: number): string {
    const title = String(item.title ?? item.label ?? `Step ${index + 1}`);
    const match = title.match(/^(\d+)[.)]\s+/);
    return type === 'steps' && match && Number(match[1]) === Number(item.step ?? index + 1)
      ? title.slice(match[0].length) : title;
  }
</script>

<section class="rich-timeline" class:rich-steps={type === 'steps'} data-rich-block-type={type}>
  {#if blockTitle(block)}<h4>{@html renderInlineMarkdown(blockTitle(block))}</h4>{/if}
  <ol>
    {#each items as item, index}
      <li class="tone-{String(item.tone ?? item.status ?? 'neutral')}">
        <span>{@html renderInlineMarkdown(String(item.time ?? item.step ?? index + 1))}</span>
        <div>
          <strong>{@html renderInlineMarkdown(itemTitle(item, index))}</strong>
          {#if item.content || item.description || item.text}<p>{@html renderInlineMarkdown(String(item.content ?? item.description ?? item.text))}</p>{/if}
        </div>
      </li>
    {/each}
  </ol>
</section>
