<script lang="ts">
  import { findTarget } from '$lib/find';
  import AgentAvatar from '$lib/components/AgentAvatar.svelte';
  import Check from 'lucide-svelte/icons/check';
  import Lock from 'lucide-svelte/icons/lock';
  import Search from 'lucide-svelte/icons/search';
  import type { AgentAccess } from '$lib/artifact-authoring';

  let { agents, selected = $bindable<string[]>([]), ownerId = null, disabled = false }: {
    agents: AgentAccess[]; selected?: string[]; ownerId?: string | null; disabled?: boolean;
  } = $props();
  let query = $state('');
  const visible = $derived(agents.filter((agent) => agent.name.toLocaleLowerCase().includes(query.toLocaleLowerCase())));
  function toggle(agent: AgentAccess) {
    selected = selected.includes(agent.agent_id)
      ? selected.filter((id) => id !== agent.agent_id) : [...selected, agent.agent_id];
  }
</script>

<div class="space-y-4">
  {#if agents.length > 6}
    <label class="flex min-h-11 items-center gap-2 rounded-xl border border-control-border bg-surface px-3">
      <Search size={16} class="text-quiet" />
      <input use:findTarget aria-label="Find agents" placeholder="Find an agent…" bind:value={query} class="min-w-0 flex-1 bg-transparent py-2 text-sm text-foreground outline-none" />
    </label>
  {/if}
  <div class="grid grid-cols-2 gap-2 sm:grid-cols-3" aria-label="Select agents">
    {#each visible as agent (agent.agent_id)}
      {@const explicit = selected.includes(agent.agent_id)}
      {@const fixed = agent.agent_id === ownerId || (agent.inherited && !explicit)}
      {@const active = explicit || agent.inherited || agent.agent_id === ownerId}
      <button type="button" aria-label={`Share with ${agent.name}`} aria-pressed={active}
        disabled={disabled || fixed} onclick={() => toggle(agent)}
        class={`group relative flex min-h-28 min-w-0 flex-col items-center gap-2 rounded-2xl border p-3 text-center transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-default ${active ? 'border-accent/60 bg-accent-subtle text-accent' : 'border-separator bg-surface/40 text-secondary hover:border-control-border hover:bg-raised/70'}`}
      >
        <AgentAvatar name={agent.name} avatarUrl={agent.avatar_url} class="!h-11 !w-11" draggable={false} />
        <span class="w-full truncate text-sm font-medium">{agent.name}</span>
        {#if agent.agent_id === ownerId}<span class="text-xs text-muted">Owner</span>
        {:else if agent.inherited}<span class="text-xs text-muted">{explicit ? 'Inherited + selected' : 'Inherited access'}</span>
        {:else}<span class="text-xs text-quiet">{explicit ? 'Selected' : 'Select'}</span>{/if}
        <span class={`absolute right-2 top-2 ${active ? 'text-accent' : 'text-transparent'}`} aria-hidden="true">
          {#if fixed}<Lock size={14} />{:else}<Check size={15} />{/if}
        </span>
      </button>
    {:else}<p class="col-span-full py-4 text-center text-sm text-quiet">{agents.length ? 'No matching agents.' : 'No active agents available.'}</p>{/each}
  </div>
</div>
