<script lang="ts">
  import type { ComponentProps } from 'svelte';
  import ChatWorkspace from '$lib/components/chat-v2/ChatWorkspace.svelte';

  let props: ComponentProps<typeof ChatWorkspace> = $props();
  let workspace: ChatWorkspace | undefined = $state();
  export function getInspectorState() {
    return workspace?.getInspectorState() ?? { open: false, controlsId: '' };
  }
  export async function toggleInspector(open?: boolean, restoreFocus = true) {
    await workspace?.toggleInspector(open, restoreFocus);
  }
  export function handleEscape(): boolean {
    return workspace?.handleEscape() ?? false;
  }
</script>

<ChatWorkspace bind:this={workspace} {...props} />
