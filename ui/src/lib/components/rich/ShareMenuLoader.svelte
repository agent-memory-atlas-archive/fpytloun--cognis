<script lang="ts">
  import { onMount } from 'svelte';
  import ViewerIcon from './ViewerIcon.svelte';
  import type { ShareLinkOptions } from './share-options';
  export let createLink: (options: ShareLinkOptions) => Promise<string>;
  export let allowModeChoice = false;
  export let defaultMode: 'view' | 'download' = 'view';
  export let label = '';
  let menu: typeof import('./ShareMenu.svelte')['default'] | null = null;
  let error = '';
  onMount(() => {
    let active = true;
    import('./ShareMenu.svelte')
      .then(module => { if (active) menu = module.default; })
      .catch(() => { if (active) error = 'Share controls could not load. Reload the page to retry.'; });
    return () => { active = false; };
  });
</script>

{#if menu}
  <svelte:component this={menu} {createLink} {allowModeChoice} {defaultMode} {label} />
{:else}
  <button type="button" aria-label="Share public link" disabled><ViewerIcon name="share" />{#if label}<span>{label}</span>{/if}</button>
  {#if error}<span role="status">{error}</span>{/if}
{/if}

<style>
  button { display: inline-grid; place-items: center; width: 34px; height: 34px; padding: 0; border: 0; border-radius: 6px; background: transparent; color: inherit; opacity: .5; }
</style>
