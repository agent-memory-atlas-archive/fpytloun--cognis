<script lang="ts">
  import '../../../src/app.css';
  import ChatMessage from '../../../src/lib/components/ChatMessage.svelte';
  import ChatV2Composer from '../../../src/lib/components/chat-v2/ChatV2Composer.svelte';
  import type { MessageTimelineItem } from '../../../src/lib/timeline-render-model';

  let value = $state('A compact message');
  const item = (role: 'user' | 'assistant'): MessageTimelineItem => ({
    id: `palette-${role}`, role, kind: 'message', seq: null, content: 'Readable **message** with `code`.',
    html: '<h2>Readable heading</h2><p>Message prose, <strong>emphasis</strong>, <a href="#reference">reference</a> and <code>inline code</code>.</p><pre><code class="hljs"><span class="hljs-keyword">const</span> text = <span class="hljs-string">"message"</span>;</code></pre>',
    timestamp: '2026-01-01T10:00:00Z',
    attachments: role === 'user' ? [{
      artifact_id: 'palette-fixture-document', filename: 'readable.txt', mime_type: 'text/plain', size_bytes: 1024,
    }] : [],
  });
</script>

<main class="h-screen overflow-auto bg-canvas p-4 text-foreground">
  <section class="mx-auto max-w-4xl space-y-4">
    <ChatMessage item={item('user')} />
    <ChatMessage item={item('assistant')} />
    <ChatV2Composer bind:value onSend={() => {}} onStop={() => {}} onFiles={() => {}} />
    <div id="reader" class="theme-palette p-2" data-theme-family="classic" data-resolved-theme="dark">
      Local reader palette
      <span id="reader-syntax" class="text-syntax-keyword">syntax</span>
    </div>
  </section>
</main>
