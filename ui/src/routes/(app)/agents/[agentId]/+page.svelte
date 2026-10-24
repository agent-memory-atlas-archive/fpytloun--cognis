<script lang="ts">
  import { page } from '$app/stores';
  import AgentDetail from '$lib/components/agents/AgentDetail.svelte';
</script>

{#key $page.params.agentId}
  <AgentDetail agentId={$page.params.agentId ?? ''} />
{/key}
