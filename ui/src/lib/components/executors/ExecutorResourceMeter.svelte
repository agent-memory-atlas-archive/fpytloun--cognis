<script lang="ts">
  let {
    label,
    value,
    detail
  } = $props<{
    label: string;
    value: number | null;
    detail: string;
  }>();

  const normalized = $derived(value == null ? null : Math.max(0, Math.min(100, value)));
  const tone = $derived(
    normalized == null
      ? 'bg-inset'
      : normalized >= 95
        ? 'bg-danger'
        : normalized >= 80
          ? 'bg-accent'
          : 'bg-success'
  );
</script>

<div class="space-y-2">
  <div class="flex items-baseline justify-between gap-3 text-sm">
    <span class="font-medium text-foreground">{label}</span>
    <span class="text-right text-xs text-muted">{detail}</span>
  </div>
  {#if normalized == null}
    <div class="h-1.5 overflow-hidden rounded-full bg-raised" aria-hidden="true">
      <div class="h-full w-0"></div>
    </div>
  {:else}
    <div
      class="h-1.5 overflow-hidden rounded-full bg-raised"
      role="progressbar"
      aria-label={label}
      aria-valuemin="0"
      aria-valuemax="100"
      aria-valuenow={Math.round(normalized)}
    >
      <div class={`h-full rounded-full transition-[width] duration-300 ${tone}`} style={`width: ${normalized}%`}></div>
    </div>
  {/if}
</div>
