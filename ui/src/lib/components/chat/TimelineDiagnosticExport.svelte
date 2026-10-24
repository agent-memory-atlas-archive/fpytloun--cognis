<script lang="ts">
  import { version } from '$app/environment';
  import Download from 'lucide-svelte/icons/download';
  import { captureClientDiagnostic, clientDiagnosticFilename } from '$lib/chat-v2/client-diagnostic';
  import Button from '$lib/components/ui/Button.svelte';
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
      anchor.download = clientDiagnosticFilename(capture.scope.conversation_id);
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

<section class="mt-4 space-y-3 border-t border-separator pt-3" aria-label="Chat diagnostics" data-testid="timeline-diagnostic-export">
  <div class="space-y-1">
    <h4 class="text-xs font-medium text-foreground">Chat diagnostics</h4>
    <p class="text-xs leading-5 text-quiet">
      Export IDs and ordering metadata from this device. No message text, tool inputs or outputs are included.
      The file stays on your device unless you share it.
    </p>
  </div>
  <Button
    variant="secondary"
    size="sm"
    class="min-h-[44px] w-full gap-2 sm:w-auto"
    disabled={!clientState.scopeKey}
    onclick={download}
  >
    <Download class="h-3.5 w-3.5" aria-hidden="true" />
    Download chat diagnostics
  </Button>
  {#if failed}<p role="alert" class="text-xs text-danger">Could not prepare the diagnostic file. Please try again.</p>{/if}
</section>
