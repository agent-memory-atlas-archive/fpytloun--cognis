<script lang="ts">
  import { api } from '$lib/api/client';
  import SessionDetailsContent from './SessionDetailsContent.svelte';
  import type { IntarisSessionDetail } from '$lib/types/api';
  import { useSectionConnectivity } from '$lib/connectivity-section.svelte';

  let {
    sessionId,
    onOpenIntaris,
    onLoaded,
  } = $props<{
    sessionId: string;
    onOpenIntaris?: ((intarisSessionId: string) => void | Promise<void>) | undefined;
    onLoaded?: ((detail: IntarisSessionDetail) => void) | undefined;
  }>();

  let detail = $state<IntarisSessionDetail | null>(null);
  let loading = $state(false);
  let error = $state('');
  let requestGeneration = 0;
  let reloadToken = $state(0);
  // Hidden while the global connection banner applies; reload on restore.
  const net = useSectionConnectivity({ hasError: () => Boolean(error), retry: () => { reloadToken += 1; } });

  $effect(() => {
    void reloadToken;
    const requestedSessionId = sessionId;
    const generation = ++requestGeneration;
    detail = null;
    error = '';
    loading = true;
    void api.sessions.intarisDetail(requestedSessionId)
      .then((value) => {
        if (generation !== requestGeneration || requestedSessionId !== sessionId) return;
        detail = value;
        onLoaded?.(value);
      })
      .catch((caught) => {
        if (generation !== requestGeneration || requestedSessionId !== sessionId) return;
        error = caught instanceof Error ? caught.message : 'Unable to load session details.';
      })
      .finally(() => {
        if (generation === requestGeneration && requestedSessionId === sessionId) loading = false;
      });
    return () => { requestGeneration += 1; };
  });
</script>

<section class="max-h-[min(70vh,calc(var(--app-viewport-height,100dvh)-8rem))] overflow-y-auto overscroll-contain border-b border-separator/80 bg-surface/40 px-4 py-4" data-testid="session-details-panel">
  {#if loading || (error && net.hideErrors)}
    <p class="text-xs text-quiet">Loading session details…</p>
  {:else if error}
    <p class="text-xs text-danger">{error}</p>
  {:else if detail}
    <SessionDetailsContent {detail} {onOpenIntaris} />
  {/if}
</section>
