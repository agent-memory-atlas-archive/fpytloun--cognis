<script lang="ts">
  import { onMount } from 'svelte';
  import FileText from 'lucide-svelte/icons/file-text';
  import { api } from '$lib/api/client';
  import type { ProjectActivity } from '$lib/types/api';

  let { artifact } = $props<{ artifact: ProjectActivity['artifacts'][number] }>();
  let container: HTMLDivElement;
  let visible = $state(false);
  let url = $state<string | null>(null);
  let failed = $state(false);

  onMount(() => {
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { visible = true; observer.disconnect(); }
    }, { rootMargin: '150px' });
    observer.observe(container);
    return () => observer.disconnect();
  });

  $effect(() => {
    const id = artifact.artifact_id;
    const image = artifact.mime_type.startsWith('image/');
    let cancelled = false;
    url = null;
    failed = false;
    if (visible && image) {
      // The view URL is an HTML viewer; use the authenticated raw-file URL for img.
      void api.artifacts.signedUrl(id, 900, 'download').then((result) => {
        if (!cancelled) url = result.url;
      }).catch(() => { if (!cancelled) failed = true; });
    }
    return () => { cancelled = true; };
  });
</script>

<div bind:this={container} class="flex h-20 w-24 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-separator bg-surface" data-testid="project-artifact-thumbnail">
  {#if url && !failed}
    <img src={url} alt="" loading="lazy" class="h-full w-full object-cover" onerror={() => { failed = true; }} />
  {:else}
    <FileText size={24} class="text-quiet" aria-hidden="true" />
  {/if}
</div>
