<script lang="ts">
  export let name: 'light' | 'dark' | 'system' | 'download' | 'copy' | 'check' | 'contents' | 'collapse' | 'close' | 'share';
</script>

<svg viewBox="0 0 16 16" fill="none" aria-hidden="true" data-viewer-icon={name}>
  {#if name === 'light'}
    <circle cx="8" cy="8" r="3.1" />
    <path d="M8 1.4v1.6M8 13v1.6M1.4 8H3M13 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M12.6 3.4l-1.1 1.1M4.5 11.5l-1.1 1.1" />
  {:else if name === 'dark'}
    <path d="M13 9.6A5.6 5.6 0 0 1 6.4 3a5.6 5.6 0 1 0 6.6 6.6Z" />
  {:else if name === 'system'}
    <rect x="2" y="3" width="12" height="8" rx="1.6" /><path d="M6 13.4h4" />
  {:else if name === 'download'}
    <path d="M8 2.5v7.5M4.8 7.2 8 10.4l3.2-3.2M3 13h10" />
  {:else if name === 'copy'}
    <rect x="5.4" y="2.6" width="8" height="8" rx="2" /><path d="M10.6 13.4H4.6a2 2 0 0 1-2-2v-6" />
  {:else if name === 'check'}
    <path d="m3 8 3 3 7-7" />
  {:else if name === 'contents'}
    <path d="M2.5 4h11M2.5 8h11M2.5 12h7" />
  {:else if name === 'collapse'}
    <path d="M9.8 4.2 6 8l3.8 3.8M13 4.2v7.6" />
  {:else if name === 'share'}
    <path d="M9 2h5v5M14 2 7 9M6 3H3v10h10v-3" />
  {:else}
    <path d="m4 4 8 8M12 4l-8 8" />
  {/if}
</svg>

<style>
  svg { width: 16px; height: 16px; stroke: currentColor; stroke-width: 1.4; stroke-linecap: round; stroke-linejoin: round; flex: none; }
</style>
