<script lang="ts">
  import ArrowLeft from 'lucide-svelte/icons/arrow-left';
  import { isPlainNavigation } from '$lib/chat-v2/navigation';
  let { conversationId, onBack } = $props<{
    conversationId: string;
    onBack: () => void;
  }>();
</script>

<a href={`/chat/${encodeURIComponent(conversationId)}`}
  class="touch-target-compact inline-flex shrink-0 items-center justify-center rounded-lg text-muted hover:bg-raised hover:text-strong"
  aria-label="Back to parent conversation"
  title="Back to parent conversation"
  onclick={(event) => { if (isPlainNavigation(event)) { event.preventDefault(); onBack(); } }}>
  <ArrowLeft class="h-4 w-4" />
</a>
