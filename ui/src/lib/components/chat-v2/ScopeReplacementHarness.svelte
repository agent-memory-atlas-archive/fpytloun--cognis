<script lang="ts">
  import { untrack, type ComponentProps } from 'svelte';
  import ScopedChatV2Timeline from './ScopedChatV2Timeline.svelte';

  let { initial }: { initial: ComponentProps<typeof ScopedChatV2Timeline> } = $props();
  // Freeze providers at mount: the button changes only parent-owned scope state.
  const api = untrack(() => initial.api);
  const realtime = untrack(() => initial.realtime);
  let scope = $state(untrack(() => initial.scope));
</script>

<button onclick={() => { scope = { ...scope }; }}>Replace equivalent scope</button>
<ScopedChatV2Timeline {scope} {api} {realtime} autoBackfill={false} />
