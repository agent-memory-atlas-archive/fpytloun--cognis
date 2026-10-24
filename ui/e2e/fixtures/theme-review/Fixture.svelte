<script lang="ts">
  import '../../../src/app.css';
  import { onMount } from 'svelte';
  import ChatMessage from '../../../src/lib/components/ChatMessage.svelte';
  import ChatV2Composer from '../../../src/lib/components/chat-v2/ChatV2Composer.svelte';
  import ToolCallBlock from '../../../src/lib/components/ToolCallBlock.svelte';
  import RecapCard from '../../../src/lib/components/chat-v2/RecapCard.svelte';
  import HookCard from '../../../src/lib/components/chat-v2/HookCard.svelte';
  import CompactionCard from '../../../src/lib/components/CompactionCard.svelte';
  import QueuedMessagesPanel from '../../../src/lib/components/chat-v2/QueuedMessagesPanel.svelte';
  import AttentionActionRenderer from '../../../src/lib/components/attention/AttentionActionRenderer.svelte';
  import AttentionActionDialog from '../../../src/lib/components/attention/AttentionActionDialog.svelte';
  import ToolCallGroupBlock from '../../../src/lib/components/chat-v2/ToolCallGroupBlock.svelte';
  import Button from '../../../src/lib/components/ui/Button.svelte';
  import UserInteractionMessage from '../../../src/lib/components/UserInteractionMessage.svelte';
  import type { ToolGroupRow } from '../../../src/lib/chat-v2/tool-groups';
  import type { RecapTimelineItem, NoticeTimelineItem, QueueMessage } from '../../../src/lib/chat-v2/types';
  import type { CompactionTimelineItem, UserInteractionTimelineItem } from '../../../src/lib/timeline-render-model';
  import type { AttentionActionDetail } from '../../../src/lib/types/api';

  let value = $state('Review this draft before sending.');
  let fullShell = $state(false);
  let restoration = $state(false);
  const detail = "Unknown category 'cognis'. Valid categories include preferences and technical.";
  const result = JSON.stringify({ error: { code: 'memory_validation_error', status_code: 422, detail,
    retry: { automatic: false, action: 'correct_arguments_then_retry', guidance: 'Correct the category then retry.' } } });
  const recap = { id: 'review-recap', kind: 'recap', text: 'Reviewed the shared presentation owners. No deployment was performed.',
    scope: 'recent_window', auto: true, deliverables: [], artifacts: [], files: [],
    source_session_id: 'review-session', source_seq: 1, stats_version: 1, file_diffs_omitted: false,
    sort_key: '1', source_refs: [], stable: true } satisfies RecapTimelineItem;
  const hook = { id: 'review-hook', kind: 'notice', title: 'Debrief', level: 'info',
    sort_key: '2', source_refs: [], stable: true,
    hook: { run_id: 'review-hook-run', hook_id: 'review-debrief', trigger: 'conversation_idle', status: 'completed', outcome: 'Updated the review notes; production is unchanged.' } } satisfies NoticeTimelineItem;
  const compacted = { id: 'review-compaction', kind: 'compaction', status: 'compacted', turnsCompacted: 12,
    method: 'llm', timestamp: null, summaryPreview: 'Earlier review work summarized.' } as CompactionTimelineItem;
  const queue = [{ queue_id: 'review-queue', content: 'Please retain the attached review notes and inspect the candidate.',
    status: 'queued', can_edit: true, attachments: [{ artifact_id: 'review-attachment', filename: 'review-notes.md', kind: 'file' }] }] as QueueMessage[];
  const managed = { id: 'review-managed-tool', kind: 'tool_call' as const, toolName: 'agent_conversation_interrupt',
    status: 'completed' as const, isError: false, timestamp: null,
    arguments: { conversation_id: 'review-local-conversation', reason: 'Local review only; production is unchanged.' },
    result: JSON.stringify({ conversation_id: 'review-local-conversation', agent_id: 'review-agent',
      status: 'interrupted', reason: 'Local review only; production is unchanged.' }) };
  const group = { id: 'review-managed-group', kind: 'tool_group', defaultExpanded: true,
    items: [{ id: managed.id, kind: 'tool_call', call_id: managed.id, tool_name: managed.toolName,
      status: 'completed', arguments: managed.arguments, is_error: false,
      sort_key: '3', source_refs: [], stable: true, attachments: [], file_diffs: [],
      truncated: false, has_full_output: true }],
    summary: { kind: 'delegate', label: 'Delegating work…', icon: 'delegate',
      accentClass: 'text-orange-tone', toolCount: 1, detailLabel: '1 tool',
      durationMs: 45, startedAt: null, failedCount: 0, deniedCount: 0, status: 'complete' },
  } as ToolGroupRow;
  const answered = { id: 'review-answered', kind: 'user_interaction', timestamp: null, interactionType: 'question',
    title: 'You answered questions', status: 'complete',
    answers: [{ question: 'Should the reviewed candidate continue with the approved local scope?', answer: 'Continue normally' }] } as UserInteractionTimelineItem;
  const collapsed = ([['explore', 'Exploring…', 'search', 'border-blue-border text-blue-tone', '10 tools'],
    ['command', 'Running commands…', 'terminal', 'border-violet-border text-violet-tone', '1 tool'],
    ['delegate', 'Delegating work…', 'delegate', 'border-orange-border text-orange-tone', '2 tools'],
    ['memory', 'Accessing memory…', 'brain', 'border-fuchsia-border text-fuchsia-tone', '1 tool']] as const)
    .map(([kind, label, icon, accentClass, detailLabel]) => ({ ...group, id: `review-collapsed-${kind}`, defaultExpanded: false,
      summary: { ...group.summary, kind, label, icon, accentClass, detailLabel } }) as ToolGroupRow);
  const question = { action_id: 'review-question', revision: 1, kind: 'step_question', title: 'Response required',
    status: 'pending', can_resolve: true, display: { questions: [{ id: 'scope', question:
      'Do you authorize completion of the local presentation review, including typography, nested tool frames, matte information cards, queued messages and readable question controls? This sample does not authorize pushing, deploying, or changing production.',
      options: [{ id: 'review', label: 'Review the local candidate only' }, { id: 'blocked', label: 'Keep production unchanged' }],
      multiple: false, required: true, allow_custom: true }] } } as unknown as AttentionActionDetail;
  onMount(() => {
    const query = new URLSearchParams(location.search);
    fullShell = query.has('full-shell');
    restoration = query.has('restoration');
    document.documentElement.dataset.themeFamily = query.get('family') ?? 'paper';
    document.documentElement.dataset.resolvedTheme = query.get('mode') ?? 'light';
  });
</script>

<main class="h-screen overflow-y-auto bg-canvas p-4 text-foreground" data-testid="review-production-components">
  <div class="mx-auto max-w-5xl space-y-4">
    <h1 class="text-lg font-semibold">Local review — production presentation components</h1>
    <ChatMessage item={{ id: 'review-user', kind: 'message', role: 'user', seq: 1, timestamp: null,
      content: 'Please review the release notes.', html: '<p>Please review the <a href="/docs">release notes</a> before continuing.</p>',
      attachments: [{ artifact_id: 'review-document', filename: 'review-notes.md', kind: 'file', mime_type: 'text/markdown', size_bytes: 128 }] }} />
    <ChatMessage item={{ id: 'review-assistant', kind: 'message', role: 'assistant', seq: 2, timestamp: null,
      content: 'The candidate is ready.', html: '<p>The candidate is ready for visual review. Reading text should remain clear without tinting the entire interface.</p><pre><code><span class="hljs-keyword">const</span> result = <span class="hljs-string">"ready"</span>;</code></pre>' }} />
    <UserInteractionMessage item={answered} />
    {#each collapsed as row (row.id)}
      <ToolCallGroupBlock {row} getToolCall={() => managed} />
    {/each}
    <ChatV2Composer bind:value onFiles={() => {}} onSend={() => {}} onStop={() => {}} />
    <QueuedMessagesPanel conversationId="review-local-conversation" messages={queue} onMutation={() => {}} />
    <CompactionCard item={compacted} />
    {#if restoration}
      <a data-testid="classic-link-foreground" href="/docs">Original link foreground</a>
      <Button>Original action foreground</Button>
      <pre><code><span class="hljs-comment">Original comment</span><span class="hljs-punctuation">;</span><span class="json-number">42</span><span class="json-boolean">true</span><span class="hljs-variable">answer</span></code></pre>
      <div data-testid="classic-failed-compaction"><CompactionCard item={{ ...compacted, id: 'review-failed-compaction', status: 'failed', error: 'Compaction failed for local paint review.' }} /></div>
      <div data-testid="classic-native-paint">
        <ToolCallBlock item={{ id: 'review-native-paint', kind: 'tool_call', callId: 'review-native-paint', toolName: 'read',
          status: 'completed', isError: false, timestamp: null, arguments: { file_path: '/repo/review.ts' },
          result: '1: const answer = 42;\n2: export { answer };' }} />
      </div>
      <div data-testid="classic-web-paint">
        <ToolCallBlock item={{ id: 'review-web-paint', kind: 'tool_call', callId: 'review-web-paint', toolName: 'web_fetch',
          status: 'completed', isError: false, timestamp: null, arguments: { url: 'https://cognis.test/review' },
          result: 'Local review content.' }} />
      </div>
      <div data-testid="classic-web-failed-paint">
        <ToolCallBlock item={{ id: 'review-web-failed-paint', kind: 'tool_call', callId: 'review-web-failed-paint', toolName: 'web_fetch',
          status: 'failed', isError: true, timestamp: null, arguments: { url: 'https://cognis.test/review' },
          result: JSON.stringify({ error: 'The review resource was unavailable.' }) }} />
      </div>
    {/if}
    <RecapCard item={recap} />
    <HookCard item={hook} />
    <ToolCallGroupBlock row={group} getToolCall={() => managed} />
    <ToolCallBlock item={{ id: 'review-memory', kind: 'tool_call', callId: 'review-memory', toolName: 'memory_add',
      status: 'failed', isError: true, timestamp: null, arguments: { content: 'Record the review.', memory_type: 'preference', categories: ['cognis'] }, result }} />
    <section class="bg-surface" aria-label="Local question preview">
      <AttentionActionRenderer action={question} onSubmit={() => {}} />
    </section>
  </div>
</main>
{#if fullShell}
  <AttentionActionDialog actionId="review-question" title="Response required" onClose={() => { fullShell = false; }} onSettled={() => {}} />
{/if}
