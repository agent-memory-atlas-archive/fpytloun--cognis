<script module lang="ts">
  export type { SessionDetailsData } from './session-details-types';
</script>

<script lang="ts">
  import { onMount } from 'svelte';
  import type SessionDetailsBody from './SessionDetailsBody.svelte';
  import type { SessionDetailsProps } from './session-details-types';
  import { loadSessionDetails } from './session-details-loader';

  let props: SessionDetailsProps = $props();
  let Body = $state.raw<typeof SessionDetailsBody | null>(null);
  let error = $state(false);
  let mounted = false;

  async function load(): Promise<void> {
    error = false;
    try {
      const loaded = await loadSessionDetails();
      if (mounted) Body = loaded;
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

{#if Body}
  <Body {...props} />
{:else if error}
  <div role="alert" class="space-y-2 text-sm text-secondary">
    <p>Could not load session details.</p>
    <button type="button" class="text-accent hover:text-accent-hover" onclick={load}>Try again</button>
  </div>
{:else}
  <p role="status" class="text-sm text-muted">Loading session details…</p>
{/if}
