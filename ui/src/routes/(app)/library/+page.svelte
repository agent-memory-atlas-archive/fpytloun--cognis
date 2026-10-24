<script lang="ts">
  import ResourceBrowser from '$lib/components/library/ResourceBrowser.svelte';
</script>

<svelte:head><title>Library · Cognis</title></svelte:head>
<section class="mx-auto w-full max-w-6xl space-y-6 px-4 py-6 sm:px-7 sm:py-8">
  <header>
    <h1 class="text-2xl font-semibold tracking-tight text-strong">Library</h1>
    <p class="mt-2 text-sm text-muted">Your work, beyond the conversation.</p>
  </header>
  <ResourceBrowser />
</section>
