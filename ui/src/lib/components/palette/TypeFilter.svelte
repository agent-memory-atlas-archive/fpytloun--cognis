<script lang="ts">
  import { tick } from 'svelte';
  import Check from 'lucide-svelte/icons/check';
  import ChevronDown from 'lucide-svelte/icons/chevron-down';
  import { resultTypes, typeLabels, type PaletteItem } from '$lib/palette/model';

  let { selected, onchange }: {
    selected: PaletteItem['kind'][];
    onchange: (types: PaletteItem['kind'][]) => void;
  } = $props();
  let open = $state(false);
  let root: HTMLDivElement;
  let trigger: HTMLButtonElement;
  const label = $derived(selected.length === resultTypes.length ? 'All types'
    : selected.length === 1 ? typeLabels[selected[0]] : `${selected.length} types`);

  function close(restore = false) {
    open = false;
    if (restore) trigger?.focus();
  }
  function toggle(type: PaletteItem['kind']) {
    onchange(selected.includes(type) ? selected.filter(item => item !== type) : [...selected, type]);
  }
  async function onKey(event: KeyboardEvent) {
    if (event.key === 'Escape' && open) {
      event.preventDefault(); event.stopPropagation(); close(true); return;
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const wasOpen = open;
    open = true;
    await tick();
    const buttons = [...root.querySelectorAll<HTMLButtonElement>('[role^="menuitem"]')];
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
      : !wasOpen || index < 0 ? (event.key === 'ArrowUp' ? buttons.length - 1 : 0)
      : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
    buttons[next]?.focus();
  }
  function outside(event: PointerEvent) {
    if (open && event.target instanceof Node && !root.contains(event.target)) close();
  }
  function focusOut(event: FocusEvent) {
    if (!root.contains(event.relatedTarget as Node | null)) close();
  }
</script>

<svelte:window onpointerdown={outside} />
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div bind:this={root} class="type-filter" data-palette-filter data-open={open} onkeydown={onKey} onfocusout={focusOut}>
  <button bind:this={trigger} type="button" class="type-trigger" aria-label="Filter result types"
    aria-haspopup="menu" aria-expanded={open} aria-controls="palette-type-menu" onclick={() => open = !open}>
    <span class="scope-dot"></span>{label}<ChevronDown size={12} />
  </button>
  {#if open}
    <div class="type-menu" id="palette-type-menu" role="menu" aria-label="Result types">
      <button type="button" role="menuitem" class="all-types" onclick={() => onchange([...resultTypes])}>All types</button>
      {#each resultTypes as type}
        <button type="button" role="menuitemcheckbox" aria-checked={selected.includes(type)} onclick={() => toggle(type)}>
          <Check size={13} style={`opacity:${selected.includes(type) ? 1 : 0}`} />{typeLabels[type]}
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .type-filter{position:relative;text-transform:none;letter-spacing:normal;font-weight:400;flex-shrink:0;}
  .type-trigger{display:flex;align-items:center;gap:6px;padding:6px 0 6px 8px;font-size:11px;color:var(--muted);border-radius:6px;}
  .type-trigger:hover,.type-trigger:focus-visible{color:var(--foreground);}
  .scope-dot{width:4px;height:4px;background:var(--accent);border-radius:50%;opacity:.8;}
  .type-menu{position:absolute;right:0;top:100%;z-index:3;width:172px;max-height:min(340px,48dvh);overflow:auto;padding:5px;border:1px solid color-mix(in srgb,var(--foreground) 18%,transparent);border-radius:12px;background:var(--elevated);box-shadow:0 12px 32px #0004;}
  .type-menu button{display:flex;align-items:center;gap:9px;width:100%;padding:8px 10px;border-radius:7px;font-size:12px;text-align:left;color:var(--muted);}
  .type-menu button:hover,.type-menu button:focus-visible{background:color-mix(in srgb,var(--foreground) 6%,transparent);color:var(--foreground);outline:none;}
  .type-menu button[aria-checked="true"]{color:var(--foreground);}
  .all-types{border-bottom:1px solid var(--separator);margin-bottom:4px;}
  @media(hover:none){.type-trigger{min-height:36px;}.type-menu button{min-height:40px;}}
</style>
