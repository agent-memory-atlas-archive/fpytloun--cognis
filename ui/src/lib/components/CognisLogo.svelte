<script lang="ts">
  import mono from '../../../static/brand/cognis-mark.svg?raw';
  import color from '../../../static/brand/cognis-mark-color.svg?raw';

  let { variant = 'color', class: className = '', label = '' }:
    { variant?: 'color' | 'mono'; class?: string; label?: string } = $props();
  const id = $props.id();
  // Only trusted build-time artwork enters this HTML sink. Scope every SVG ID.
  const artwork = $derived((variant === 'mono' ? mono : color)
    .replace(/id="([^"]+)"/g, (_, name) => `id="${id}-${name}"`)
    .replace(/url\(#([^)]+)\)/g, (_, name) => `url(#${id}-${name})`)
    .replace('<svg ', '<svg aria-hidden="true" focusable="false" '));
</script>

<span class={`cognis-logo ${className}`} role={label ? 'img' : undefined}
  aria-label={label || undefined} aria-hidden={label ? undefined : 'true'}>
  {@html artwork}
</span>

<style>
  :where(.cognis-logo) { width: 1em; height: 1em; }
  .cognis-logo { display: inline-block; vertical-align: middle; flex-shrink: 0; }
  .cognis-logo :global(svg) { display: block; width: 100%; height: 100%; }
  @media (forced-colors: active) {
    .cognis-logo :global(svg), .cognis-logo :global(circle) { fill: currentColor; }
  }
</style>
