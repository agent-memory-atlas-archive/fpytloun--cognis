<script lang="ts">
  import Bell from 'lucide-svelte/icons/bell';
  import { inbox } from '$lib/stores/inbox';
  let { expanded = false }: { expanded?: boolean } = $props();
</script>

<a href="/notifications" class="relative inline-flex min-h-10 items-center justify-center gap-2 rounded-xl px-3 text-secondary transition hover:bg-raised hover:text-strong" aria-label={`Notifications${$inbox.unreadCount ? `, ${$inbox.unreadCount} unread` : ''}`} title="Notifications">
  <Bell class="h-4 w-4 shrink-0" />
  {#if expanded}<span class="text-sm">Notifications</span>{/if}
  {#if $inbox.unreadCount}
    <span class="rounded-full bg-accent px-1.5 text-[10px] font-semibold leading-5 text-on-accent">{$inbox.unreadCount > 99 ? '99+' : $inbox.unreadCount}</span>
  {/if}
</a>
