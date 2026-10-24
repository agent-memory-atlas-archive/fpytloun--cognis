<script lang="ts">
  import BlockingDialog from '$lib/components/ui/BlockingDialog.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { api } from '$lib/api/client';

  let {
    name = '',
    description = '',
    personality = {},
    onAccept,
    onClose
  } = $props<{
    name: string;
    description?: string;
    personality?: Record<string, unknown>;
    onAccept: (imageId: string, avatarUrl: string) => void;
    onClose: () => void;
  }>();

  let prompt = $state('');
  let generatingPrompt = $state(false);
  let generatingImage = $state(false);
  let generatedImageUrl = $state('');
  let generatedImageId = $state('');
  let error = $state('');

  async function generatePrompt() {
    generatingPrompt = true;
    error = '';
    try {
      const result = await api.images.generatePrompt({ name, description, personality });
      prompt = result.prompt;
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to generate prompt';
    } finally {
      generatingPrompt = false;
    }
  }

  async function generateImage() {
    if (!prompt.trim()) return;
    generatingImage = true;
    error = '';
    generatedImageUrl = '';
    generatedImageId = '';
    try {
      const result = await api.images.generate(prompt);
      generatedImageId = result.image_id;
      generatedImageUrl = result.url;
      if (result.prompt_used && result.prompt_used !== prompt) {
        prompt = result.prompt_used;
      }
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to generate image';
    } finally {
      generatingImage = false;
    }
  }

  function handleAccept() {
    if (generatedImageId && generatedImageUrl) {
      onAccept(generatedImageId, generatedImageUrl);
    }
  }

  // Auto-generate prompt on mount
  $effect(() => {
    if (!prompt && name) {
      generatePrompt();
    }
  });
</script>
<BlockingDialog label="Generate avatar" onClose={onClose} titleId="avatar-generate-title">
  {#snippet header()}
    <div class="flex items-center justify-between gap-3">
      <h3 class="text-lg font-semibold text-foreground" id="avatar-generate-title">Generate Avatar</h3>
      <button type="button" class="text-muted hover:text-foreground" onclick={onClose}>&times;</button>
    </div>
  {/snippet}

  {#snippet children()}
    <div>
      <!-- Prompt section -->
      <div class="mb-4">
      <div class="mb-2 flex items-center justify-between">
        <label class="text-sm font-medium text-foreground" for="avatar-prompt">Prompt</label>
        <button
          type="button"
          class="flex items-center gap-1 text-xs text-accent hover:text-accent-hover disabled:opacity-50"
          onclick={generatePrompt}
          disabled={generatingPrompt}
        >
          {#if generatingPrompt}
            <span class="inline-block h-3 w-3 animate-spin rounded-full border border-control-border border-t-accent"></span>
          {/if}
          Regenerate prompt
        </button>
      </div>
      <textarea
        id="avatar-prompt"
        bind:value={prompt}
        class="min-h-[100px] w-full rounded-2xl border border-control-border bg-canvas/80 px-4 py-3 text-sm text-foreground placeholder:text-quiet"
        placeholder="Describe the avatar you want to generate..."
        disabled={generatingPrompt}
      ></textarea>
    </div>

      <!-- Preview section -->
      <div class="mb-4">
      <p class="mb-2 text-sm font-medium text-foreground">Preview</p>
      <div class="flex h-48 items-center justify-center rounded-2xl border border-control-border bg-canvas/80">
        {#if generatingImage}
          <div class="flex flex-col items-center gap-2 text-muted">
            <span class="inline-block h-8 w-8 animate-spin rounded-full border-2 border-control-border border-t-accent"></span>
            <span class="text-sm">Generating...</span>
          </div>
        {:else if generatedImageUrl}
          <img
            src={generatedImageUrl}
            alt="Generated avatar"
            class="h-full max-h-44 rounded-xl object-contain"
          />
        {:else}
          <span class="text-sm text-quiet">No image generated yet</span>
        {/if}
      </div>
    </div>

      <!-- Error -->
      {#if error}
        <p class="mb-4 text-sm text-danger">{error}</p>
      {/if}
    </div>
  {/snippet}

  {#snippet footer()}
    <div class="flex items-center justify-end gap-3">
      <Button variant="secondary" onclick={onClose}>Cancel</Button>
      <Button
        variant="secondary"
        onclick={generateImage}
        disabled={generatingImage || !prompt.trim()}
      >
        {generatingImage ? 'Generating...' : generatedImageUrl ? 'Regenerate' : 'Generate'}
      </Button>
      {#if generatedImageId}
        <Button variant="primary" onclick={handleAccept}>Use this avatar</Button>
      {/if}
    </div>
  {/snippet}
</BlockingDialog>
