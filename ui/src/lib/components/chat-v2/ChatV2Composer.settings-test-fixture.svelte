<script lang="ts">
  import ChatV2Composer from './ChatV2Composer.svelte';
  let { active = false } = $props<{ active?: boolean }>();
</script>

<ChatV2Composer {active} onSend={() => {}} onStop={() => {}} onFiles={() => {}}>
  {#snippet settings()}
    <button type="button" aria-label="Chat settings">Settings</button>
  {/snippet}
</ChatV2Composer>
