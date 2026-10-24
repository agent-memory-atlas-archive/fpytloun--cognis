<script lang="ts">
  // Public standalone publications must not import authenticated favorites or API state.
  let { kind, id, initial }: { kind?: string; id?: string; initial?: unknown } = $props();
</script>
