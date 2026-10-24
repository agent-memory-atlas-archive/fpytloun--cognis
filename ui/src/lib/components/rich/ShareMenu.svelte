<script lang="ts">
  import ViewerIcon from './ViewerIcon.svelte';
  import PublicLinkDialog from './PublicLinkDialog.svelte';
  import type { ShareLinkOptions } from './share-options';
  import './document-actions.css';
  export let createLink: (options: ShareLinkOptions) => Promise<string>;
  export let allowModeChoice = false;
  export let defaultMode: 'view' | 'download' = 'view';
  let open = false;
  let copied = false;
</script>

<button class="document-icon-action" type="button" aria-label="Share public link" title="Share public link" aria-haspopup="dialog" aria-expanded={open} on:click={() => { open = true; copied = false; }}>
  <span data-testid={copied ? 'rich-share-copied-icon' : 'rich-share-icon'}><ViewerIcon name={copied ? 'check' : 'share'} /></span>
</button>
{#if open}
  <PublicLinkDialog {createLink} {allowModeChoice} {defaultMode} onClose={() => { open = false; }} onCopied={() => { copied = true; }} />
{/if}
