<script lang="ts">
  import type { Snippet } from 'svelte';

  import Popover from './Popover.svelte';

  /**
   * Thin wrapper around Popover that keeps the historical `<Tooltip>` API.
   *
   * Semantics:
   *   - On devices with hover (desktop), reveals on mouse/keyboard hover.
   *   - On touch devices, reveals on tap — no longer unreachable.
   */

  let {
    text,
    children,
    placement = 'top',
    class: className = '',
    showOnTouch = true,
  } = $props<{
    text: string;
    children: Snippet;
    placement?: 'top' | 'bottom' | 'left' | 'right';
    class?: string;
    showOnTouch?: boolean;
  }>();
</script>

<Popover {text} {placement} class={className} {showOnTouch}>{@render children()}</Popover>
