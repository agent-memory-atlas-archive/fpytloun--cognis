<script lang="ts">
  import { onMount } from 'svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { postNative } from '$lib/native/host';
  import { nativeNotificationStatus } from '$lib/native/notification-status';
  const refresh = () => postNative('notification-settings', { action: 'status' });
  onMount(() => {
    refresh();
    window.addEventListener('focus', refresh);
    return () => window.removeEventListener('focus', refresh);
  });
</script>
<section class="space-y-4 rounded-2xl border border-separator p-5" aria-label="macOS notifications">
  <h2 class="text-lg font-semibold">macOS notifications</h2>
  <p>Delivered by the native Cognis app, not browser Web Push. No server push subscription is required.</p>
  <p role="status">{$nativeNotificationStatus.message}</p>
  <dl>
    <dt>macOS authorization</dt><dd>{$nativeNotificationStatus.authorization}</dd>
    {#if $nativeNotificationStatus.errorDomain}
      <dt>System error</dt><dd>{$nativeNotificationStatus.errorDomain} ({$nativeNotificationStatus.errorCode})</dd>
    {/if}
  </dl>
  <div class="flex gap-2">
    <Button onclick={() => postNative('notification-settings', { action: 'show' })}>
      {$nativeNotificationStatus.authorization === 'not-determined' && !$nativeNotificationStatus.errorDomain
        ? 'Enable Notifications…' : 'Open Notification Settings…'}
    </Button>
    <Button variant="secondary" onclick={refresh}>Refresh status</Button>
  </div>
  <p class="text-sm text-muted">Enabling permission requires your confirmation in the native dialog. A denied permission cannot be overridden by Cognis. Development signing or macOS policy can also prevent authorization.</p>
</section>
