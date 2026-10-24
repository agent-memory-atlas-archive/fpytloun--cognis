<script lang="ts">
  import { goto } from '$app/navigation';

  let { error, status } = $props();

  function message(): string {
    return error instanceof Error ? error.message : 'Unexpected application error';
  }

  async function goHome(): Promise<void> {
    await goto('/');
  }
</script>

<svelte:head>
  <title>Application Error · Cognis</title>
</svelte:head>

<div class="app-fullscreen-safe flex items-center justify-center overflow-y-auto">
  <div class="w-full max-w-xl rounded-3xl border border-danger-border bg-surface p-8 shadow-card">
    <p class="text-sm font-medium uppercase tracking-[0.3em] text-danger">Error {status}</p>
    <h1 class="mt-3 text-3xl font-semibold text-strong">Something went wrong</h1>
    <p class="mt-4 text-sm leading-6 text-secondary">{message()}</p>
    <div class="mt-8 flex flex-wrap gap-3">
      <button
        class="rounded-xl bg-accent px-4 py-2 text-sm font-medium text-on-accent transition hover:bg-accent-hover"
        onclick={goHome}
      >
        Return home
      </button>
    </div>
  </div>
</div>
