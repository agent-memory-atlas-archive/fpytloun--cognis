<script lang="ts">
  import { findTarget } from '$lib/find';
  import { tick } from 'svelte';
  import { portal } from '$lib/actions/portal';
  import ChevronDown from 'lucide-svelte/icons/chevron-down';
  import Check from 'lucide-svelte/icons/check';

  let { options, value, onchange, label = 'Target', disabled = false }: {
    options: { value: string; modelId: string; providerId: string; label: string }[];
    value: string;
    onchange: (value: string) => void;
    label?: string;
    disabled?: boolean;
  } = $props();
  const id = $props.id();
  let open = $state(false);
  let query = $state('');
  let active = $state(0);
  let root = $state<HTMLDivElement>();
  let trigger = $state<HTMLButtonElement>();
  let search = $state<HTMLInputElement>();
  let panel = $state<HTMLDivElement>();
  function floating(node: HTMLDivElement) {
    const position = () => {
      if (!trigger) return;
      const rect = trigger.getBoundingClientRect();
      const width = Math.min(Math.max(rect.width, 256), window.innerWidth - 16);
      const below = window.innerHeight - rect.bottom - 12;
      const above = rect.top - 12;
      const upward = below < Math.min(node.scrollHeight, 320) && above > below;
      const height = Math.max(0, upward ? above : below);
      node.style.width = `${width}px`;
      node.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))}px`;
      node.style.maxHeight = `${height}px`;
      node.style.top = upward ? 'auto' : `${rect.bottom + 4}px`;
      node.style.bottom = upward ? `${window.innerHeight - rect.top + 4}px` : 'auto';
    };
    position();
    window.addEventListener('resize', position);
    window.addEventListener('scroll', position, true);
    const observer = new ResizeObserver(position);
    observer.observe(node);
    if (trigger) observer.observe(trigger);
    return { destroy() {
      window.removeEventListener('resize', position);
      window.removeEventListener('scroll', position, true);
      observer.disconnect();
    }};
  }
  const selected = $derived(options.find(option => option.value === value));
  const filtered = $derived(options.filter(option =>
    `${option.label} ${option.value}`.toLowerCase().includes(query.trim().toLowerCase())
  ));
  async function toggle() {
    open = !open;
    if (open) {
      query = ''; active = 0;
      await tick();
      search?.focus();
    }
  }
  function close() { open = false; trigger?.focus(); }
  function select(next: string) { onchange(next); close(); }
  function keydown(event: KeyboardEvent) {
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      active = Math.max(0, Math.min(filtered.length - 1, active + (event.key === 'ArrowDown' ? 1 : -1)));
      document.getElementById(`${id}-${active}`)?.scrollIntoView?.({ block: 'nearest' });
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      if (filtered[active]) select(filtered[active].value);
    }
    if (event.key === 'Tab') open = false;
  }
</script>

<svelte:window onpointerdown={(event) => {
  if (open && event.target instanceof Node && !root?.contains(event.target) && !panel?.contains(event.target)) open = false;
}} />
<div class="relative min-w-0" bind:this={root}>
  <label for={`${id}-trigger`} class="text-sm">{label}</label>
  <button id={`${id}-trigger`} type="button" bind:this={trigger} {disabled}
    aria-haspopup="listbox" aria-expanded={open} aria-controls={`${id}-list`}
    onclick={toggle}
    class="mt-1 flex w-full items-center justify-between gap-2 rounded border border-control-border bg-canvas p-2 text-left disabled:opacity-50">
    <span class="min-w-0 truncate">{selected?.label ?? (value !== '/' ? value : 'Choose provider/model')}</span>
    <ChevronDown size={16} class="shrink-0 text-muted" />
  </button>
  {#if open}
    <div bind:this={panel} use:portal use:floating data-find-scope
      class="fixed z-[100] flex flex-col overflow-hidden rounded-lg border border-control-border bg-elevated p-2 shadow-overlay">
      <input use:findTarget bind:this={search} bind:value={query} oninput={() => active = 0}
        onkeydown={keydown} role="combobox" aria-label={`Search ${label.toLowerCase()} models`}
        aria-expanded="true" aria-controls={`${id}-list`} aria-autocomplete="list"
        aria-activedescendant={filtered.length ? `${id}-${active}` : undefined}
        placeholder="Search models or providers…" class="mb-2 w-full shrink-0 rounded border border-control-border bg-canvas p-2 text-sm" />
      <div id={`${id}-list`} role="listbox" aria-label={`${label} models`} class="min-h-0 max-h-64 overflow-y-auto">
        {#each filtered as option, index (option.value)}
          <button type="button" role="option" tabindex="-1" id={`${id}-${index}`}
            aria-selected={option.value === value} onclick={() => select(option.value)}
            onpointermove={() => active = index}
            class={`flex w-full items-center justify-between gap-2 rounded p-2 text-left ${active === index ? 'bg-inset' : 'hover:bg-raised'}`}>
            <span class="min-w-0"><span class="block truncate text-sm font-medium">{option.modelId}</span>
              <span class="block truncate text-xs text-muted">{option.providerId}</span></span>
            {#if option.value === value}<Check size={16} class="shrink-0 text-success" />{/if}
          </button>
        {:else}
          <p role="status" class="p-3 text-sm text-muted">No matching models</p>
        {/each}
      </div>
    </div>
  {/if}
</div>
