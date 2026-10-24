<script lang="ts">
  import { onMount } from 'svelte';
  import { version as appVersion } from '$app/environment';
  import Card from '$lib/components/ui/Card.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { addToast } from '$lib/stores/toasts';
  import { clearOfflineData, requestPersistentStorage } from '$lib/offline/cache';
  import { clearPerfLog, readPerfLog, type PerfLogEntry } from '$lib/perf-log';

  let perfEntries = $state<PerfLogEntry[]>([]);
  let perfOpen = $state(false);

  function loadPerf(): void {
    perfEntries = readPerfLog().slice().reverse();
  }

  function formatTime(at: number): string {
    return new Date(at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  let usageLabel = $state('unknown');
  let persisted = $state<boolean | null>(null);
  let busy = $state(false);

  function formatBytes(value: number): string {
    if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }

  async function refresh(): Promise<void> {
    try {
      const estimate = await navigator.storage?.estimate?.();
      usageLabel = typeof estimate?.usage === 'number' ? formatBytes(estimate.usage) : 'unknown';
      persisted = (await navigator.storage?.persisted?.()) ?? null;
    } catch {
      usageLabel = 'unknown';
    }
  }

  async function keepData(): Promise<void> {
    persisted = await requestPersistentStorage();
  }

  async function clearData(): Promise<void> {
    busy = true;
    try {
      await clearOfflineData();
      addToast('Offline data cleared from this device.', 'success');
      await refresh();
    } finally {
      busy = false;
    }
  }

  onMount(() => {
    void refresh();
  });
</script>

<Card class="space-y-4 p-5">
  <div>
    <p class="text-xs uppercase tracking-[0.25em] text-muted">Offline</p>
    <h2 class="mt-1 text-lg font-semibold text-strong">Offline data</h2>
    <p class="mt-2 text-sm leading-6 text-muted">
      Recent conversations, the conversation list, and viewed images are kept on this device so the app opens instantly and stays readable offline. The data is removed when you log out.
    </p>
  </div>
  <div class="space-y-2 rounded-2xl border border-separator bg-canvas/70 p-4 text-sm">
    <div class="flex items-center justify-between gap-3">
      <span class="text-muted">Storage used by Cognis</span>
      <span class="text-foreground" data-testid="offline-storage-usage">{usageLabel}</span>
    </div>
    <div class="flex items-center justify-between gap-3">
      <span class="text-muted">Protected from eviction</span>
      <span class={persisted ? 'text-success' : 'text-secondary'}>{persisted === null ? 'unknown' : persisted ? 'yes' : 'no'}</span>
    </div>
    <div class="flex items-center justify-between gap-3">
      <span class="text-muted">App build</span>
      <span class="font-mono text-xs text-secondary" data-testid="app-build-version">{appVersion}</span>
    </div>
  </div>
  <div class="flex flex-wrap gap-2">
    {#if persisted === false}
      <Button variant="secondary" onclick={keepData}>Keep data on this device</Button>
    {/if}
    <Button variant="secondary" onclick={clearData} disabled={busy}>Clear offline data</Button>
    <Button variant="secondary" onclick={() => { perfOpen = !perfOpen; loadPerf(); }}>
      {perfOpen ? 'Hide' : 'Show'} loading diagnostics
    </Button>
  </div>
  {#if perfOpen}
    <div class="space-y-2 rounded-2xl border border-separator bg-canvas/70 p-4 text-xs" data-testid="perf-log">
      {#if perfEntries.length === 0}
        <p class="text-muted">No loading events recorded yet.</p>
      {:else}
        <table class="w-full text-left tabular-nums">
          <thead class="text-quiet">
            <tr><th class="pb-1">Time</th><th>Event</th><th>Path</th><th class="text-right">ms</th></tr>
          </thead>
          <tbody class="text-foreground">
            {#each perfEntries as entry, index (`${entry.at}-${index}`)}
              <tr>
                <td class="pr-2 text-muted">{formatTime(entry.at)}</td>
                <td class="pr-2">{entry.kind}</td>
                <td class="pr-2">{entry.path}{entry.detail ? ` (${entry.detail})` : ''}</td>
                <td class="text-right">{entry.ms}</td>
              </tr>
            {/each}
          </tbody>
        </table>
        <Button variant="secondary" size="sm" onclick={() => { clearPerfLog(); loadPerf(); }}>Clear diagnostics</Button>
      {/if}
    </div>
  {/if}
</Card>
