<script lang="ts">
  import Link from 'lucide-svelte/icons/link';
  import Check from 'lucide-svelte/icons/check';
  import ShareMenu from './ShareMenuLoader.svelte';
  import type { ShareLinkOptions } from './share-options';
  import './document-actions.css';
  import type { Snippet } from 'svelte';
  let { internalUrl, createLink, allowModeChoice = true, defaultMode = 'view', extraActions, shareLabel = '' }: {
    internalUrl: string; createLink?: ((options: ShareLinkOptions) => Promise<string>) | null;
    allowModeChoice?: boolean; defaultMode?: 'view' | 'download';
    extraActions?: Snippet;
    shareLabel?: string;
  } = $props();
  let copied = $state(false);
  let error = $state('');
  $effect(() => { void internalUrl; copied = false; error = ''; });
  async function copy() {
    try { await navigator.clipboard.writeText(new URL(internalUrl, location.origin).href); copied = true; }
    catch { error = 'Could not copy the internal link.'; }
  }
</script>
{@render extraActions?.()}
<button class="document-icon-action" type="button" aria-label={copied ? 'Internal link copied' : 'Copy internal link'} title={copied ? 'Internal link copied' : 'Copy internal link'} onclick={copy}>
  {#if copied}<Check size={18} />{:else}<Link size={18} />{/if}
</button>
{#if createLink}<ShareMenu {createLink} {allowModeChoice} {defaultMode} label={shareLabel} />{/if}
{#if error}<span role="status" class="text-xs text-danger">{error}</span>{/if}
