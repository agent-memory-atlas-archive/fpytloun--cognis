<script lang="ts">
  import { version } from '$app/environment';
  import Download from 'lucide-svelte/icons/download';
  import { captureClientDiagnostic } from '$lib/chat-v2/client-diagnostic';
  import type { ChatV2ClientState } from '$lib/chat-v2/sync-engine';
  import type { TimelineItem } from '$lib/chat-v2/types';

  let { clientState, visibleItems }: { clientState: ChatV2ClientState; visibleItems: TimelineItem[] } = $props();
  let failed = $state(false);

  function download(): void {
    failed = false;
    let url: string | null = null;
    const anchor = document.createElement('a');
    try {
      const capture = captureClientDiagnostic(clientState, visibleItems, {
        build: version,
        standalone: window.matchMedia('(display-mode: standalone)').matches,
        online: navigator.onLine,
      });
      url = URL.createObjectURL(new Blob([JSON.stringify(capture, null, 2)], { type: 'application/json' }));
      anchor.href = url;
      anchor.download = 'cognis-chat-diagnostic.json';
      document.body.appendChild(anchor);
      anchor.click();
    } catch {
      failed = true;
    } finally {
      anchor.remove();
      // Safari can consume the download after the click handler returns.
      if (url) {
        const downloadUrl = url;
        window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 60_000);
      }
    }
  }
</script>

<details class="rounded-lg border border-border p-3 text-xs" data-testid="timeline-diagnostic-export">
  <summary class="cursor-pointer text-muted">Chat diagnostics</summary>
  <p class="mt-2 text-quiet">
    Export IDs and ordering metadata from this device. No message text, tool inputs or outputs are included.
    The file stays on your device unless you share it.
  </p>
  <button
    type="button"
    class="mt-3 inline-flex min-h-10 items-center gap-2 rounded-lg border border-border px-3 text-muted transition hover:bg-surface-hover hover:text-strong disabled:opacity-50"
    disabled={!clientState.scopeKey}
    onclick={download}
  >
    <Download class="h-3.5 w-3.5" />
    Download chat diagnostics
  </button>
  {#if failed}<p role="alert" class="mt-2 text-danger">Could not prepare the diagnostic file. Please try again.</p>{/if}
</details>
