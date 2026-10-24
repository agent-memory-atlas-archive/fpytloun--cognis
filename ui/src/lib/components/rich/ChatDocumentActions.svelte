<script lang="ts">
  import type { Snippet } from 'svelte';
  import DownloadMenu from './DownloadMenu.svelte';
  import ShareMenu from './ShareMenuLoader.svelte';
  import ViewerIcon from './ViewerIcon.svelte';
  import type { ShareLinkOptions } from './share-options';

  export let openFullView: () => void;
  export let copyDocument: () => void;
  export let copied = false;
  export let pdfUrl = '';
  export let htmlUrl = '';
  export let markdownUrl = '';
  export let internalUrl = '';
  export let createLink: ((options: ShareLinkOptions) => Promise<string>) | null | undefined = undefined;
  export let collapsible = false;
  export let expanded = true;
  export let toggleExpanded: () => void;
  export let extraActions: Snippet | undefined = undefined;
  let more: HTMLDetailsElement;

  function dismiss(event: PointerEvent) {
    if (more?.open && event.target instanceof Node && !more.contains(event.target)) more.open = false;
  }
  function escape(event: KeyboardEvent) {
    if (event.key !== 'Escape' || !more?.open) return;
    event.stopPropagation();
    more.open = false;
    more.querySelector('summary')?.focus();
  }
  function run(action: () => void) {
    more.open = false;
    more.querySelector('summary')?.focus();
    action();
  }
  function focusLeft(event: FocusEvent) {
    if (event.relatedTarget instanceof Node && !more.contains(event.relatedTarget)) more.open = false;
  }
</script>

<svelte:window on:pointerdown={dismiss} on:keydown={escape} />
<nav class="chat-document-actions" aria-label="Document actions">
  <button class="copy-icon-button" type="button" aria-label="Open fullscreen" title="Open fullscreen" on:click={openFullView}>
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5" /></svg>
  </button>
  {#if pdfUrl || htmlUrl || markdownUrl}<DownloadMenu {pdfUrl} {htmlUrl} {markdownUrl} />{/if}
  {#if createLink}<ShareMenu {createLink} />{/if}
  <details class="chat-document-more" bind:this={more} on:focusout={focusLeft}>
    <summary class="copy-icon-button" aria-label="More document actions" title="More document actions">
      <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><circle cx="3" cy="8" r="1.2" /><circle cx="8" cy="8" r="1.2" /><circle cx="13" cy="8" r="1.2" /></svg>
    </summary>
    <div class="chat-document-menu">
      <button type="button" on:click={() => run(copyDocument)}><ViewerIcon name={copied ? 'check' : 'copy'} />{copied ? 'Copied' : 'Copy document'}</button>
      {#if collapsible}<button type="button" on:click={() => run(toggleExpanded)}><ViewerIcon name={expanded ? 'collapse' : 'expand'} />{expanded ? 'Collapse document' : 'Expand document'}</button>{/if}
      {#if internalUrl}<a href={internalUrl}>Open in Library ↗</a>{/if}
      {@render extraActions?.()}
    </div>
  </details>
  <span class="sr-only" role="status">{copied ? 'Document copied' : ''}</span>
</nav>
