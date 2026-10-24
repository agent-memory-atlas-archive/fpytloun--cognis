<script lang="ts">
  let { error } = $props();

  function message(): string {
    return error instanceof Error ? error.message : 'Unable to render this page';
  }
</script>

<section class="mx-auto max-w-4xl px-6 py-16">
  <div class="rounded-3xl border border-danger-border bg-surface p-8 shadow-card">
    <p class="text-sm font-medium uppercase tracking-[0.3em] text-danger">Page Error</p>
    <h1 class="mt-3 text-2xl font-semibold text-strong">This section could not be loaded</h1>
    <p class="mt-4 text-sm leading-6 text-secondary">{message()}</p>
  </div>
</section>
