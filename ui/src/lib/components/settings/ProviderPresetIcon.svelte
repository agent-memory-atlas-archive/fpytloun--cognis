<script lang="ts">
  let { preset }: { preset: string } = $props();
  const logos: Record<string, string> = {
    openrouter: '/providers/openrouter.svg',
    openai: '/providers/openai.svg',
    anthropic: '/providers/anthropic.svg',
    chatgpt: '/providers/codex.svg'
  };
</script>

<span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-raised text-foreground" aria-hidden="true">
  {#if logos[preset]}
    <img src={logos[preset]} alt="" width="24" height="24" class="h-6 w-6 invert" />
  {:else}
    <svg viewBox="0 0 32 32" class="h-6 w-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="m11 7-8 9 8 9m10-18 8 9-8 9M18 4l-4 24" />
    </svg>
  {/if}
</span>
