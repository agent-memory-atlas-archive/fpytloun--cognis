<script lang="ts">
  import type { KnowledgebaseDocumentModel } from '$lib/types/api';
  let { doc, metadataSchema = {} }: { doc: KnowledgebaseDocumentModel; metadataSchema?: Record<string, unknown> } = $props();
  const fields = $derived((metadataSchema.fields && typeof metadataSchema.fields === 'object' ? metadataSchema.fields : {}) as Record<string, { display?: boolean }>);
  const entries = $derived(Object.entries(doc.metadata).filter(([key]) => key !== 'source_path' && fields[key]?.display !== false));
</script>
<aside class="rounded-xl border border-separator/80 bg-canvas/40 p-3 text-sm" data-testid="knowledge-document-metadata">
  <h4 class="font-semibold text-strong">Details</h4>
  <dl class="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
    <dt class="text-quiet">Path</dt><dd class="break-all text-secondary">{doc.source_path ?? doc.display_name}</dd>
    <dt class="text-quiet">Type</dt><dd class="text-secondary">{doc.mime_type ?? 'Unknown'}</dd>
    <dt class="text-quiet">Status</dt><dd class="text-secondary">{doc.status}</dd>
    <dt class="text-quiet">Chunks</dt><dd class="text-secondary">{doc.chunk_count}</dd>
  </dl>
  {#if entries.length}
    <div class="mt-3 border-t border-separator pt-3">
      {#each entries as [key, value] (key)}
        <div class="mb-2"><p class="text-xs text-quiet">{key}</p>
          {#if Array.isArray(value)}<div class="flex flex-wrap gap-1">{#each value as item}<span class="rounded-full bg-raised px-2 py-0.5 text-xs">{String(item)}</span>{/each}</div>
          {:else if value && typeof value === 'object'}<details><summary class="cursor-pointer text-xs">Structured value</summary><pre class="mt-1 overflow-x-auto whitespace-pre-wrap text-xs">{JSON.stringify(value, null, 2)}</pre></details>
          {:else}<p class="text-xs text-secondary">{String(value)}</p>{/if}
        </div>
      {/each}
    </div>
  {/if}
</aside>
