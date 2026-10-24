<script lang="ts">
  import TimelineViewport from './TimelineViewport.svelte';

  let { onJumpToActiveStart } = $props<{
    onJumpToActiveStart: (request: { scrollTop: number; rowKey: string | null }) => void;
  }>();
  let userScrolledUp = $state(true);
</script>

<TimelineViewport
  items={[]}
  bind:userScrolledUp
  autoScrollOnResize={false}
  testId="timeline-jump-viewport"
  {onJumpToActiveStart}
>
  {#snippet children()}
    <div data-timeline-row-key="row-a"><div data-kind="message" data-role="assistant" data-testid="message-a">A</div></div>
    <div data-timeline-row-key="tool"><div data-kind="tool_call">tool</div></div>
    <div data-timeline-row-key="row-b"><div data-kind="message" data-role="assistant" data-testid="message-b">{'B'.repeat(400)}</div></div>
  {/snippet}
</TimelineViewport>
