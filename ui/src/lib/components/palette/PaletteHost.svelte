<script lang="ts">
  import { onMount, tick } from 'svelte';
  import type CommandPalette from './CommandPalette.svelte';
  import { addToast } from '$lib/stores/toasts';
  import { get } from 'svelte/store';
  import { overlayStack } from '$lib/stores/overlays';

  // Keep the palette off chat's critical bundle path, but warm it during idle
  // time so the normal shortcut path never waits for a module download.
  let Component = $state<typeof CommandPalette>();
  let instance = $state<CommandPalette>();
  let loading: Promise<void> | null = null;
  let alive = true;
  async function load() {
    loading ??= import('./CommandPalette.svelte').then(async (module) => {
      if (!alive) return;
      Component = module.default;
      await tick();
    }).catch((error) => { loading = null; throw error; });
    await loading;
  }
  export async function show() {
    try {
      await load();
      if (alive) await instance?.show();
    } catch {
      if (alive) addToast('Search could not load. Please try again.', 'error');
    }
  }
  onMount(() => {
    const warm = () => { void load().catch(() => {}); };
    const supportsIdle = typeof window.requestIdleCallback === 'function';
    const idle = supportsIdle ? window.requestIdleCallback(warm, { timeout: 1500 }) : window.setTimeout(warm, 350);
    function coldShortcut(event: KeyboardEvent) {
      if (instance || event.isComposing || event.repeat || event.altKey || event.shiftKey
        || !(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'k') return;
      if (get(overlayStack).length) return;
      event.preventDefault(); event.stopImmediatePropagation();
      void show();
    }
    window.addEventListener('keydown', coldShortcut, true);
    return () => {
      alive = false;
      if (supportsIdle) window.cancelIdleCallback(idle); else clearTimeout(idle);
      window.removeEventListener('keydown', coldShortcut, true);
    };
  });
</script>

{#if Component}<Component bind:this={instance} />{/if}
