<script lang="ts">
  import { page } from '$app/stores';
  import ChangelogView from '$lib/components/ChangelogView.svelte';
  import changelog from '$lib/generated/changelog.json';
</script>

<svelte:head>
  <title>What's new · Cognis</title>
</svelte:head>

<ChangelogView
  releases={changelog.releases}
  initialSince={$page.url.searchParams.get('since') ?? ''}
  initialThrough={$page.url.searchParams.get('through') ?? ''}
/>
