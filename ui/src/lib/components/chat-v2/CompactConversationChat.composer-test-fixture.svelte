<script lang="ts">
  import type { AttachmentRef } from '$lib/types/api';
  let { ariaLabel = 'Composer', value = $bindable(''), attachments = $bindable<AttachmentRef[]>([]),
    stopping = false, onSend, onStop, onInput, onFiles }:
    { ariaLabel?: string; value?: string; attachments?: AttachmentRef[]; stopping?: boolean;
      onSend?: () => void; onStop?: () => void; onInput?: () => void; onFiles?: (files: File[]) => void } = $props();
</script>

<input aria-label="Composer text" bind:value oninput={() => onInput?.()} />
<span data-testid="fixture-attachments">{attachments.map((ref) => ref.filename).join(',')}</span>
<button type="button" onclick={() => onFiles?.([new File(['synthetic'], 'synthetic.png', { type: 'image/png' })])}>Attach fixture</button>
<button type="button" data-testid="compact-composer-fixture" onclick={onSend}>{ariaLabel}</button>
<button type="button" disabled={stopping} onclick={onStop}>Stop fixture turn</button>
