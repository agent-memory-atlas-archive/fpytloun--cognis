<script lang="ts">
  import { goto } from '$app/navigation';
  import Bell from 'lucide-svelte/icons/bell';
  import Check from 'lucide-svelte/icons/check';
  import { inbox, markInboxRead, refreshInbox, setInboxUnreadOnly } from '$lib/stores/inbox';
  import type { InboxItem } from '$lib/types/api';
  import { useSectionConnectivity } from '$lib/connectivity-section.svelte';

  let { compact = false }: { compact?: boolean } = $props();
  const unreadOnly = $derived($inbox.unreadOnly);
  const visible = $derived($inbox.items.filter((item) => !(compact || unreadOnly) || !item.read_at));
  const displayed = $derived(compact ? visible.slice(0, 3) : visible);
  const net = useSectionConnectivity({ hasError: () => Boolean($inbox.error), retry: refreshInbox });
  const showError = $derived(Boolean($inbox.error) && !net.hideErrors);
  async function open(item: InboxItem): Promise<void> {
    if (!item.read_at) await markInboxRead([item.notification_id]);
    // Notifications never authorize access; destination routes check current grants.
    if (item.href.startsWith('/') && !item.href.startsWith('//') && !item.href.includes('\\')) void goto(item.href);
  }
</script>

<section class="min-w-0 rounded-2xl border border-separator bg-canvas/50" aria-label="Notification inbox">
  <header class="flex flex-wrap items-center justify-between gap-2 border-b border-separator px-4 py-3">
    <div class="flex items-center gap-2">
      <Bell class="h-4 w-4 text-accent" />
      <h2 class="font-medium text-strong">Notifications</h2>
      {#if $inbox.unreadCount}<span class="text-xs text-accent">{$inbox.unreadCount} unread</span>{/if}
    </div>
    <div class="flex items-center gap-3 text-xs">
      {#if compact}
        <a href="/notifications" class="text-accent hover:text-strong">View all</a>
      {:else}
        <button type="button" class="text-secondary hover:text-strong" disabled={$inbox.loading} onclick={() => void refreshInbox()}>Refresh</button>
        <button type="button" class="text-accent hover:text-strong disabled:text-quiet" disabled={!displayed.some((item) => !item.read_at)} onclick={() => void markInboxRead(displayed.filter((item) => !item.read_at).map((item) => item.notification_id))}>Mark displayed as read</button>
      {/if}
    </div>
  </header>
  {#if !compact}
    <div class="flex gap-2 px-4 py-3 text-xs">
      <button type="button" aria-pressed={!unreadOnly} class={`rounded-lg px-3 py-1.5 ${!unreadOnly ? 'bg-raised text-strong' : 'text-muted'}`} onclick={() => setInboxUnreadOnly(false)}>All</button>
      <button type="button" aria-pressed={unreadOnly} class={`rounded-lg px-3 py-1.5 ${unreadOnly ? 'bg-raised text-strong' : 'text-muted'}`} onclick={() => setInboxUnreadOnly(true)}>Unread</button>
    </div>
  {/if}
  {#if showError}
    <div class="px-4 py-3 text-sm text-danger" role="alert">{$inbox.error} <button class="underline" type="button" onclick={() => void refreshInbox()}>Retry</button></div>
  {/if}
  <ul class="divide-y divide-separator/70">
    {#each displayed as item (item.notification_id)}
      <li class={`flex items-start gap-2 px-4 py-3 ${!item.read_at ? 'bg-accent-subtle' : ''}`}>
        <span class={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${item.read_at ? 'bg-transparent' : 'bg-accent'}`} aria-label={item.read_at ? 'Read' : 'Unread'}></span>
        <button type="button" class="min-w-0 flex-1 text-left" onclick={() => void open(item)}>
          <span class="block text-sm font-medium text-foreground">{item.title}</span>
          <span class="mt-1 block break-words text-xs leading-relaxed text-muted">{item.body}</span>
          <time datetime={item.created_at} class="mt-1 block text-[11px] text-quiet">{new Date(item.created_at).toLocaleString()}</time>
        </button>
        {#if !item.read_at}
          <button type="button" class="rounded-lg p-2 text-muted hover:bg-raised hover:text-strong" aria-label={`Mark ${item.title} as read`} onclick={() => void markInboxRead([item.notification_id])}><Check class="h-4 w-4" /></button>
        {/if}
      </li>
    {/each}
  </ul>
  {#if !displayed.length && !showError}
    <p class="px-4 py-5 text-sm text-quiet" role="status">{$inbox.loading || $inbox.error ? 'Loading notifications…' : unreadOnly ? 'You’re all caught up.' : compact ? 'Open the inbox to see older unread notifications.' : 'No notifications yet.'}</p>
  {/if}
  {#if !compact && $inbox.cursor}
    <div class="border-t border-separator p-3 text-center"><button type="button" class="text-sm text-accent disabled:text-quiet" disabled={$inbox.loading} onclick={() => void refreshInbox(true)}>{$inbox.loading ? 'Loading…' : 'Load older notifications'}</button></div>
  {/if}
</section>
