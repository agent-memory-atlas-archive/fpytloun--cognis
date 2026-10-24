<script lang="ts">
  let { conversationId }: { conversationId: string } = $props();
</script>
<output data-testid="compact-conversation">{conversationId}</output>
