<script lang="ts">
  let { files, additions = 0, deletions = 0, compact = false }: {
    files?: number | null;
    additions?: number | null;
    deletions?: number | null;
    compact?: boolean;
  } = $props();
</script>

<span class="inline-flex flex-wrap items-center gap-1.5 font-mono text-[10px]" data-testid="diff-stat">
  {#if files !== undefined && files !== null}
    <span class="text-secondary">{files} {files === 1 ? 'file' : 'files'}</span>
  {/if}
  {#if additions}<span class="text-success" aria-label={`${additions} additions`}>+{additions}</span>{/if}
  {#if deletions}<span class="text-danger" aria-label={`${deletions} deletions`}>−{deletions}</span>{/if}
  {#if !compact && files == null && !additions && !deletions}<span class="text-quiet">No file changes</span>{/if}
</span>
