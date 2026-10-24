<script lang="ts">
  import { isNativeHost } from '$lib/native/host';
  import PinnedConversationDock from '$lib/components/chat/PinnedConversationDock.svelte';
</script>

{#if isNativeHost()}
  <PinnedConversationDock nativeRail />
{/if}
