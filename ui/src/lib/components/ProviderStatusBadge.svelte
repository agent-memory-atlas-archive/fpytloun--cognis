<script lang="ts">
  let { status } = $props<{ status: string }>();

  function normalizedStatus(): string {
    return status.trim().toLowerCase();
  }

  function tone(): string {
    const normalized = normalizedStatus();
    return normalized === 'healthy' || normalized === 'active'
      ? 'border-success-border bg-success-subtle text-success'
      : normalized === 'degraded'
        ? 'border-warning-border bg-warning-subtle text-warning'
        : normalized === 'disabled' || normalized === 'unknown'
          ? 'border-control-border bg-surface/80 text-secondary'
          : 'border-danger-border bg-danger-subtle text-danger';
  }
</script>

<span class={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] ${tone()}`}>
  {status}
</span>
