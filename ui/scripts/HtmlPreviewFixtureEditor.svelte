<script lang="ts">
  import TextDocument from '../src/lib/components/TextDocument.svelte';
  import type { DocumentLease } from '../src/lib/document-coordination';
  let { text, lease }: { text: string; lease: DocumentLease } = $props();
  let preview = $state(true);
  export function toggle() { preview = !preview; }
</script>
<TextDocument {text} mime="text/html" editing {preview} htmlLease={lease} />
