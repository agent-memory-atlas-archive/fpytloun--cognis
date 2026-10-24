<script lang="ts">
  import type { LegacyComposerInput } from '$lib/chat-v2/composer-hydration';
  import type { ChatMode } from '$lib/chat-v2/types';
  let { candidates, onSelect }: {
    candidates: LegacyComposerInput[];
    onSelect: (candidate: LegacyComposerInput, mode: ChatMode | null) => void;
  } = $props();
  let mode = $state('inherit');
</script>

{#if candidates.length}
  <p>Recovered draft may already have been sent. Its original send identity is unavailable.</p>
  <label>Mode for new message
    <select bind:value={mode}>
      <option value="inherit">Inherit current conversation/profile mode</option>
      <option value="default">Default (one turn)</option>
      <option value="plan">Plan</option>
      <option value="build">Build</option>
    </select>
  </label>
  {#each candidates as candidate}
    {#if candidates.length > 1}
      <p>{candidate.source === 'full' ? 'Full chat' : 'Compact chat'}: {candidate.input.text}
        ({candidate.input.attachments.length} attachments)</p>
    {/if}
    <button type="button" onclick={() => onSelect(candidate, mode === 'inherit' ? null : mode as ChatMode)}>
      {candidates.length === 1 ? 'Send as new' : `Use ${candidate.source} draft as new`}
    </button>
  {/each}
{/if}
