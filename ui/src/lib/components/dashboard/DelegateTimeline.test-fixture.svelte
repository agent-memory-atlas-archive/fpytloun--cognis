<script lang="ts">
  import type { TimelineScope } from '$lib/chat-v2/types';
  let { scope, onViewSession } = $props<{
    scope: TimelineScope;
    onViewSession?: (sessionId: string) => void | Promise<void>;
  }>();
</script>

<div data-testid="delegate-timeline" data-scope={scope.key}>
  {#if onViewSession}
    <button onclick={() => onViewSession?.('session-delegate')}>View delegate session</button>
  {/if}
</div>
