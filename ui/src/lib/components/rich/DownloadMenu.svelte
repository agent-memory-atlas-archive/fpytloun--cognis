<script lang="ts">
  import ViewerIcon from './ViewerIcon.svelte';
  import { keepInViewport } from '$lib/actions/keep-in-viewport';
  import './document-actions.css';

  export let pdfUrl = '';
  export let htmlUrl = '';
  export let markdownUrl = '';
  export let label = '';

  let root: HTMLDetailsElement;

  function close() {
    root.open = false;
  }

  function onWindowPointerDown(event: PointerEvent) {
    if (root?.open && event.target instanceof Node && !root.contains(event.target)) close();
  }

  function onWindowKeydown(event: KeyboardEvent) {
    if (root?.open && event.key === 'Escape') {
      close();
      root.querySelector('summary')?.focus();
      event.stopPropagation();
    }
  }

  function onMenuKeydown(event: KeyboardEvent) {
    if (root.open && event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      close();
      root.querySelector('summary')?.focus();
    }
  }
</script>

<svelte:window on:pointerdown={onWindowPointerDown} on:keydown={onWindowKeydown} />

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<details bind:this={root} class="download-menu" on:keydown|capture={onMenuKeydown}>
  <summary class="document-icon-action" aria-label="Download document" title="Download document"><ViewerIcon name="download" />{#if label}<span>{label}</span>{/if}</summary>
  <!-- Re-measured when the menu opens (ResizeObserver sees it become visible). -->
  <div class="download-options" aria-label="Download format" use:keepInViewport>
    {#if pdfUrl}<a href={pdfUrl} on:click={close}>PDF</a>{/if}
    {#if htmlUrl}<a href={htmlUrl} on:click={close}>Single HTML</a>{/if}
    {#if markdownUrl}<a href={markdownUrl} on:click={close}>Markdown</a>{/if}
  </div>
</details>

<style>
  .download-menu { position: relative; flex: none; }
  /* Trigger size follows the host toolbar (--rich-action-size). */
  summary { padding: 0; list-style: none; }
  summary::-webkit-details-marker { display: none; }
  summary :global(svg) { width: 20px; height: 20px; }
  summary:focus-visible, .download-options a:focus-visible { outline: 2px solid var(--rich-accent, rgb(var(--color-accent))); outline-offset: 3px; }
  .download-options { position: absolute; z-index: 20; right: 0; top: calc(100% + 6px); min-width: 160px; padding: 5px; border: 1px solid var(--rich-line, rgb(var(--color-separator))); border-radius: 9px; background: var(--rich-surface-raised, rgb(var(--color-surface))); box-shadow: 0 12px 30px #0007; }
  .download-options a { display: flex; align-items: center; padding: 9px 12px; border-radius: 6px; color: var(--rich-text, rgb(var(--color-foreground))); text-decoration: none; white-space: nowrap; font-size: 13px; }
  .download-options a:hover { background: var(--rich-control-active, rgb(var(--color-surface-hover))); }
  @media (pointer: coarse) { .download-options a { min-height: 44px; } }
</style>
