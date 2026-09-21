<script lang="ts">
  import type { TocItem, TocNode } from './publication';

  export let nodes: TocNode[] = [];
  export let activeAnchor = '';
  export let onNavigate: (item: TocItem) => void;
</script>

<ol>
  {#each nodes as node}
    <li data-level={node.item.level}>
      <button
        type="button"
        class:active={activeAnchor === node.item.anchor}
        aria-current={activeAnchor === node.item.anchor ? 'location' : undefined}
        on:click={() => onNavigate(node.item)}
      >
        {#if node.item.level === 2 && /^\d+\s/.test(node.item.label)}
          <span class="toc-number">{node.item.label.match(/^\d+/)?.[0]}</span><span>{node.item.label.replace(/^\d+\s+/, '')}</span>
        {:else}{node.item.label}{/if}
      </button>
      {#if node.children.length > 0}
        <svelte:self nodes={node.children} {activeAnchor} {onNavigate} />
      {/if}
    </li>
  {/each}
</ol>

<style>
  ol { display: grid; gap: 1px; margin: 0; padding: 0; list-style: none; }
  li > :global(ol) { padding-left: 22px; }
  button { width: 100%; min-height: 32px; border: 0; border-radius: 0; background: transparent; color: var(--rich-muted); padding: 7px 12px; font: 500 13px/1.45 var(--rich-font-sans); text-align: left; }
  li[data-level="3"] > button { font-size: 12.5px; padding-block: 5px; font-weight: 400; line-height: 1.4; min-height: 27px; }
  li[data-level="4"] > button { font-size: 12px; font-weight: 400; }
  button:hover, button:focus-visible, button.active { background: color-mix(in srgb, var(--rich-accent) 12%, transparent); color: var(--rich-text); outline: none; }
  button.active { box-shadow: inset 2px 0 var(--rich-accent); }
  button { display: flex; gap: 10px; }
  .toc-number { font: 500 11.5px/1.6 var(--rich-font-mono); padding-top: 1px; }
  /* Kept in sync with RichToc's drawer breakpoint (min-width: 1440px in
     RichDeliverable.svelte): this list renders inside the drawer at every
     width below that, including tablets, so its touch targets should stay
     comfortably tappable there too, not just on phones. */
  @media (pointer: coarse), (max-width: 959.98px) {
    button { min-height: 2.75rem; font-size: .88rem; }
    li[data-level="3"] > button { font-size: .84rem; }
    li[data-level="4"] > button { font-size: .8rem; }
  }
</style>
