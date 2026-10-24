<script lang="ts">
  import { onMount, type ComponentProps } from 'svelte';
  import RichDeliverable from '$lib/components/rich/RichDeliverable.svelte';
  import type { ShareLinkOptions } from '$lib/components/rich/share-options';
  import { installSelectionCopy } from '$lib/selection-copy';
  export let viewerProps: ComponentProps<typeof RichDeliverable>;
  let createShare: ((options: ShareLinkOptions) => Promise<string>) | null = null;
  // Keep native WebKit copy from promoting colon-prefixed prose to a URL.
  // This also applies to anonymous viewers and downloaded offline HTML.
  onMount(() => installSelectionCopy());
  onMount(() => {
    if (viewerProps.exportMode) return;
    const abort = new AbortController();
    const id = viewerProps.instanceId;
    if (!id || !/^dlv_[A-Za-z0-9_]+$/.test(id)) return;
    fetch(`/api/v1/deliverables/${encodeURIComponent(id)}/viewer-context`, { credentials: 'same-origin', signal: abort.signal })
      .then(async response => {
        if (!response.ok) return;
        const context = await response.json();
        if (context.share_link_url !== `/api/v1/deliverables/${encodeURIComponent(id)}/share-link`) return;
        createShare = async options => {
          const result = await fetch(context.share_link_url, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(options),
          });
          if (!result.ok) throw new Error('Could not create share link');
          return (await result.json()).url;
        };
      })
      .catch(() => { /* Optional owner authentication must not block public viewing. */ });
    return () => abort.abort();
  });
</script>

<RichDeliverable {...viewerProps} shareLinkCallback={createShare} />
