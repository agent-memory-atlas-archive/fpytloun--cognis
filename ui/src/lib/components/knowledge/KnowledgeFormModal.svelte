<script lang="ts">
  import Button from '$lib/components/ui/Button.svelte';
  import Input from '$lib/components/ui/Input.svelte';
  import Sheet from '$lib/components/ui/Sheet.svelte';
  import type { KnowledgebaseModel } from '$lib/types/api';

  let {
    open,
    kb = null,
    busy = false,
    error = '',
    onClose,
    onSubmit
  }: {
    open: boolean;
    kb?: KnowledgebaseModel | null;
    busy?: boolean;
    error?: string;
    onClose: () => void;
    onSubmit: (values: { name: string; description: string }) => void;
  } = $props();

  let name = $state('');
  let description = $state('');

  $effect(() => {
    if (open) {
      name = kb?.name ?? '';
      description = kb?.description ?? '';
    }
  });

  function submit(event: SubmitEvent): void {
    event.preventDefault();
    if (!name.trim()) return;
    onSubmit({ name: name.trim(), description: description.trim() });
  }
</script>

<Sheet {open} {onClose} side="center" label={kb ? 'Edit knowledgebase' : 'Create knowledgebase'} dismissible={!busy} backdropDismissible={name === (kb?.name ?? '') && description === (kb?.description ?? '')}>
  {#snippet header()}
    <h2 class="text-lg font-semibold text-strong">{kb ? 'Edit knowledgebase' : 'New knowledgebase'}</h2>
    <p class="mt-1 text-sm text-muted">
      {kb ? 'Update the name and description.' : 'Give it a name. You can add documents right after.'}
    </p>
  {/snippet}

  {#snippet children()}
    <form class="flex flex-col gap-4" onsubmit={submit}>
      <label class="flex flex-col gap-1.5 text-sm text-secondary">
        Name
        <Input bind:value={name} placeholder="e.g. Product docs" required maxlength={200} data-testid="kb-form-name" />
      </label>
      <label class="flex flex-col gap-1.5 text-sm text-secondary">
        Description <span class="text-quiet">(optional)</span>
        <textarea
          class="min-h-[88px] w-full rounded-xl border border-control-border bg-canvas/80 px-3 py-2.5 text-sm text-foreground placeholder:text-quiet"
          bind:value={description}
          placeholder="What is this knowledgebase for?"
          data-testid="kb-form-description"
        ></textarea>
      </label>

      {#if error}
        <p class="rounded-xl border border-danger-border bg-danger-subtle px-3 py-2 text-sm text-danger" role="alert">{error}</p>
      {/if}

      <div class="mt-2 flex justify-end gap-3">
        <Button type="button" variant="secondary" disabled={busy} onclick={onClose}>Cancel</Button>
        <Button type="submit" disabled={busy || !name.trim()} data-testid="kb-form-submit">
          {busy ? 'Saving…' : kb ? 'Save changes' : 'Create knowledgebase'}
        </Button>
      </div>
    </form>
  {/snippet}
</Sheet>
