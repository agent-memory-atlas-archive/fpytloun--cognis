<script lang="ts">
  let { testId = 'workspace-veil' } = $props<{ testId?: string }>();
</script>

<div
  aria-hidden="true"
  class="pointer-events-none fixed inset-0 bg-canvas/10 backdrop-blur-[1px] motion-safe:transition-opacity motion-safe:duration-150"
  data-testid={testId}
></div>
