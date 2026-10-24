<script lang="ts">
  let { label = 'Loading…', description = 'Please wait while Cognis prepares this view.' } = $props<{
    label?: string;
    description?: string;
  }>();
</script>

<div class="flex min-h-[280px] flex-col items-center justify-center gap-4 rounded-3xl border border-separator/80 bg-surface px-6 py-12 text-center shadow-card">
  <div class="h-10 w-10 animate-spin rounded-full border-2 border-control-border border-t-accent"></div>
  <div class="space-y-2">
    <h2 class="text-lg font-semibold text-strong">{label}</h2>
    <p class="max-w-md text-sm leading-6 text-muted">{description}</p>
  </div>
</div>
