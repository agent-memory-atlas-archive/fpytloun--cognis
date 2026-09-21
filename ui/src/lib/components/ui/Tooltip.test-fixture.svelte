<script lang="ts">
  import Tooltip from './Tooltip.svelte';

  let { showOnTouch = true }: { showOnTouch?: boolean } = $props();
</script>

<Tooltip text="Toolbar tooltip" {showOnTouch}>
  <button type="button" aria-label="Toolbar action">Action</button>
</Tooltip>
