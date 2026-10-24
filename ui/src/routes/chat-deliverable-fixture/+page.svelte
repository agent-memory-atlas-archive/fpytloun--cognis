<script lang="ts">
  import { page } from '$app/state';
  import ChatMessage from '$lib/components/ChatMessage.svelte';
  import AssistantDeliverableBlock from '$lib/components/AssistantDeliverableBlock.svelte';
  import type { Deliverable } from '$lib/types/api';
  import type { MessageTimelineItem } from '$lib/timeline-render-model';
  import { renderMarkdown } from '$lib/markdown';

  const deliverable: Deliverable = {
    deliverable_id: 'chat-flow-review',
    title: 'Release readiness',
    format: 'rich',
    step_run_id: null, version: 2, attempt_number: 1, target: null,
    outputs: {}, status: 'approved', evaluator_feedback: null,
    created_at: null, updated_at: null,
    content: 'The release is ready for staging. Verify recovery before production.',
    revision: 2, latest_revision: 2, is_latest: true,
    lineage_id: 'chat-flow-review', latest_deliverable_id: 'chat-flow-review',
    rich_payload: {
      blocks: [
        { type: 'hero', title: 'Release readiness', subtitle: 'The implementation is ready for staging. Recovery remains the production gate.',
          badges: page.url.searchParams.has('tones') ? ['neutral', 'info', 'success', 'warning', 'danger'].map(tone => ({ label: tone, tone })) : [] },
        { type: 'markdown', content: '## What changed\n\nThe new connection handler preserves the current conversation during a reconnect. Pending messages stay queued until the server confirms that the session is ready.\n\nThis keeps the common path simple without hiding failures. Operators can distinguish a temporary network interruption from an authorization error.' },
        { type: 'table', title: 'Acceptance checks', columns: ['Area', 'Evidence', 'Result'], rows: [
          ['Message ordering', 'Replay matches the live event stream', 'Passed'],
          ['Reconnect', 'Queued messages delivered once', 'Passed'],
          ['Recovery', 'Staging restart exercise', 'Pending'],
        ] },
        { type: 'callout', tone: 'warning', title: 'Before production', content: 'Run the recovery exercise in staging and confirm that pending messages survive a restart.' },
        ...(page.url.searchParams.has('tones') ? ['neutral', 'info', 'success', 'danger'].map(tone => ({
          type: 'callout', tone, title: `${tone} status`, content: 'Semantic status with readable text and a subdued surface.',
        })) : []),
      ],
      metadata: { toc: { enabled: true } },
    },
  };
  const introductionText = 'The reconnect change is complete. Here is the release assessment and the one remaining check.';
  const introduction: MessageTimelineItem = {
    id: 'chat-flow-introduction', kind: 'message', role: 'assistant',
    content: introductionText, html: renderMarkdown(introductionText), seq: null,
    timestamp: '2026-01-01T12:00:00Z', attachments: [],
  };
</script>

<svelte:head><title>Chat deliverable presentation</title></svelte:head>
<main class="h-screen overflow-y-auto overflow-x-hidden bg-canvas text-foreground">
  <section class="mx-auto w-full px-4 py-8 sm:px-8" class:max-w-5xl={!page.url.searchParams.has('wide')} data-testid="chat-deliverable-preview">
    <ChatMessage item={introduction} />
    <AssistantDeliverableBlock conversational
      item={{ id: 'chat-flow-output', kind: 'assistant_deliverable', deliverableId: deliverable.deliverable_id, format: 'rich', title: deliverable.title }}
      loadDeliverable={async () => deliverable}
    />
  </section>
</main>
