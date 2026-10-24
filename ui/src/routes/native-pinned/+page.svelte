<script lang="ts">
  import { page } from '$app/stores';
  import { isNativeHost } from '$lib/native/host';
  import { auth } from '$lib/stores/auth';
  import NativePinnedPresentation from '$lib/native/NativePinnedPresentation.svelte';
  import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';
  import ToastViewport from '$lib/components/ToastViewport.svelte';
  import { deviceDataReady } from '$lib/offline/session';
  import NativeDirectConversation from '$lib/components/chat/NativeDirectConversation.svelte';

</script>

{#if isNativeHost() && $auth.status === 'authenticated' && $deviceDataReady}
  <ConfirmDialog />
  <ToastViewport />
  <main class="h-dvh min-h-0 overflow-hidden" data-testid="native-pinned-surface">
    {#key $auth.user?.email}
    {#if $page.url.searchParams.has('direct') && $page.url.searchParams.get('agent')}
      {#key $page.url.searchParams.get('agent')}
      <NativeDirectConversation agentId={$page.url.searchParams.get('agent')!} />
      {/key}
    {:else}<NativePinnedPresentation />
    {/if}
    {/key}
  </main>
{:else}<p class="p-4 text-muted">Sign in through the main Cognis window.</p>{/if}
