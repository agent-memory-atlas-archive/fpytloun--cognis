<script lang="ts">
  import type { SlashCommandSuggestion } from '$lib/types/api';

  let {
    suggestions,
    selectedIndex,
    listboxId,
    onSelect,
  } = $props<{
    suggestions: SlashCommandSuggestion[];
    selectedIndex: number;
    listboxId: string;
    onSelect: (event: MouseEvent, index: number) => void;
  }>();
</script>

<div
  id={listboxId}
  class="mb-1 max-h-[40vh] overflow-y-auto overscroll-contain rounded-xl border border-control-border bg-elevated/95 py-1 text-sm shadow-lg"
  role="listbox"
  aria-label="Slash command suggestions"
>
  {#each suggestions as suggestion, index}
    <button
      id={`${listboxId}-option-${index}`}
      class="flex w-full items-center gap-3 px-3 py-1.5 text-left text-xs transition {index === selectedIndex ? 'bg-accent-subtle text-foreground' : 'text-secondary hover:bg-surface-hover hover:text-foreground'}"
      onmousedown={(event) => event.preventDefault()}
      onclick={(event) => onSelect(event, index)}
      type="button"
      role="option"
      aria-selected={index === selectedIndex}
    >
      <span class="min-w-0 font-mono font-medium text-accent">
        {suggestion.kind === 'parameter' ? suggestion.value : suggestion.command}
      </span>
      <span class="min-w-0 flex-1 truncate opacity-70">
        {#if suggestion.kind === 'parameter' && suggestion.label !== suggestion.value}
          {suggestion.label}
          {#if suggestion.description}<span class="opacity-60"> — {suggestion.description}</span>{/if}
        {:else}
          {suggestion.description}
        {/if}
      </span>
      {#if suggestion.badges.length > 0}
        <span class="flex shrink-0 gap-1">
          {#each suggestion.badges as badge}
            <span class="rounded-full border border-control-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-secondary">{badge}</span>
          {/each}
        </span>
      {/if}
    </button>
  {/each}
</div>
