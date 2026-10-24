<script lang="ts">
  import TimelineDiagnosticExport from '$lib/components/chat/TimelineDiagnosticExport.svelte';
  import { emptyChatV2State } from '$lib/chat-v2/sync-engine';
  import { conversationTimelineScope, type MessageTimelineItem } from '$lib/chat-v2/types';

  const scope = conversationTimelineScope('diagnostic-fixture');
  const item: MessageTimelineItem = {
    id: 'user:diagnostic-fixture', kind: 'message', role: 'user', message_id: 'diagnostic-fixture',
    content: 'Synthetic message body excluded from diagnostics', attachments: [], partial: false,
    stable: false, source_refs: [], status: 'complete',
    sort_key: '9995:000000000000001:000000:00:000000000',
  };
  const state = {
    ...emptyChatV2State(), scope, scopeKey: scope.key, conversationId: scope.conversation_id ?? null,
    localItems: [item],
  };
</script>

<main class="mx-auto max-w-lg p-6">
  <h1 class="mb-4">Synthetic timeline diagnostic fixture</h1>
  <TimelineDiagnosticExport clientState={state} visibleItems={[item]} />
</main>
