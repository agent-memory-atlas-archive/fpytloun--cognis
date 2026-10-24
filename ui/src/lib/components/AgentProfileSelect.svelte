<script lang="ts">
  import type { Agent } from '$lib/types/api';
  import { profileOptionsForAgent } from '$lib/agents';

  export let agents: Agent[] = [];
  export let agentId = '';
  export let value = '';
  export let label = 'Agent profile';
  export let help = 'Leave empty to use the selected agent default profile.';
  export let disabled = false;

  $: selectedAgent = agents.find((agent) => agent.agent_id === agentId) ?? null;
  $: profileOptions = profileOptionsForAgent(selectedAgent);
</script>

<label class="block space-y-2 text-sm font-medium text-foreground">
  <span>{label}</span>
  <select
    bind:value
    disabled={disabled || !selectedAgent || profileOptions.length === 0}
    class="w-full rounded-xl border border-control-border bg-surface px-3 py-2 text-sm text-foreground focus:border-accent disabled:opacity-50"
  >
    <option value="">Default profile</option>
    {#if value && !profileOptions.some((profile) => profile.profileId === value)}
      <option value={value}>{value}</option>
    {/if}
    {#each profileOptions as profile}
      <option value={profile.profileId}>{profile.label}</option>
    {/each}
  </select>
  {#if help}
    <small class="block text-xs font-normal text-quiet">{help}</small>
  {/if}
</label>
