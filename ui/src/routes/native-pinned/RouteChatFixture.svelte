<script lang="ts">
  import { onMount } from 'svelte';
  let { conversationId, onInitialLoaded }: { conversationId: string; onInitialLoaded?: () => void } = $props();
  onMount(() => { onInitialLoaded?.(); });
</script>
<output data-testid={`fixture-${conversationId}`}>{conversationId}</output>
