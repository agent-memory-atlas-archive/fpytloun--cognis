<script lang="ts">
  import { page } from '$app/stores';
  import KnowledgeWorkspace from '$lib/components/knowledge/KnowledgeWorkspace.svelte';
</script>

{#key $page.params.kbId}
  <KnowledgeWorkspace kbId={$page.params.kbId ?? ''} />
{/key}
