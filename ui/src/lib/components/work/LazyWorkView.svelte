<script lang="ts">
  import { onMount, type ComponentProps } from 'svelte';
  import type WorkView from './WorkView.svelte';
  import { loadWorkView } from './work-view-loader';

  let props: ComponentProps<typeof WorkView> = $props();
  let View = $state.raw<typeof WorkView | null>(null);
  let error = $state(false);
  let mounted = false;

  async function load(): Promise<void> {
    error = false;
    try {
      const loaded = await loadWorkView();
      if (mounted) View = loaded;
    } catch {
      if (mounted) error = true;
    }
  }

  onMount(() => {
    mounted = true;
    void load();
    return () => { mounted = false; };
  });
</script>

{#if View}
  <View {...props} />
{:else if error}
  <div role="alert" class="space-y-2 text-sm text-secondary">
    <p>Could not load the Work inspector.</p>
    <button type="button" class="text-accent hover:text-accent-hover" onclick={load}>Try again</button>
  </div>
{:else}
  <p role="status" class="text-sm text-muted">Loading Work inspector…</p>
{/if}
