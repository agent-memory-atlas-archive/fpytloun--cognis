<script lang="ts">
  import '../../../src/app.css';
  import TimelineOngoingWorkDrawer from '../../../src/lib/components/timeline/TimelineOngoingWorkDrawer.svelte';
  import type { BackgroundWorkItem } from '../../../src/lib/types/api';
  let selected = $state('');
  const work: BackgroundWorkItem[] = [
    { kind: 'background_command', work_id: 'shell-preview', controller_conversation_id: 'conv-root',
      session_id: 'sess-root', title: `Preview ${'very-long-title-'.repeat(12)}`,
      agent_id: 'laforge', status: 'running', todos: [] },
    { kind: 'delegated_session', work_id: 'sess-review', controller_conversation_id: 'conv-root',
      session_id: 'sess-review', title: 'Subsession review', agent_id: 'system:code-review',
      status: 'completed', todos: [] },
  ];
</script>
<main class="min-w-0 p-2">
  <TimelineOngoingWorkDrawer todos={[]} {work} open={true} onViewSession={(id) => { selected = id; }} />
  <p aria-label="Selected session">{selected}</p>
</main>
