<script lang="ts">
  import RichIcon from './RichIcon.svelte';
  import ViewerIcon from './ViewerIcon.svelte';
  import { viewerTheme, setViewerTheme } from './viewer-theme';

  export let title = '';
  export let identity: unknown = undefined;
  export let pdfUrl = '';
  export let copied = false;
  export let onCopy: () => void;
  export let onDownload: () => void = () => {};
  export let progress = 0;
  export let showProgress = true;
  $: authored = identity && typeof identity === 'object' ? identity as Record<string, unknown> : {};
  $: label = typeof authored.label === 'string' ? authored.label.trim() : '';
  const icons = new Set(['activity', 'alert', 'calendar', 'check', 'clock', 'external', 'info', 'trend_down', 'trend_up', 'arrow_up_right']);
  $: authoredIcon = authored.icon && typeof authored.icon === 'object'
    ? authored.icon as Record<string, unknown>
    : {};
  $: icon = typeof authoredIcon.name === 'string' && icons.has(authoredIcon.name)
    ? authoredIcon.name
    : '';
  $: iconAlt = typeof authoredIcon.alt === 'string' ? authoredIcon.alt.trim() : '';
</script>

<header class="viewer-chrome" data-testid="rich-viewer-chrome">
  <div class="viewer-chrome-inner">
  {#if label || icon}
    <span class="viewer-identity" data-testid="rich-viewer-identity">
      {#if icon}<RichIcon {icon} label={label ? '' : iconAlt} />{/if}
      {#if label}<span>{label}</span>{/if}
    </span>
  {/if}
  <span class="viewer-title" title={title}>{title}</span>
  <nav aria-label="Viewer controls">
    <div class="theme-controls" role="group" aria-label="Viewer theme">
      {#each ['light', 'dark', 'system'] as theme}
        <button class="theme-control" type="button" aria-label={theme === 'system' ? 'Follow system theme' : `${theme === 'light' ? 'Light' : 'Dark'} theme`} aria-pressed={$viewerTheme === theme} title={theme} on:click={() => setViewerTheme(theme === 'light' ? 'light' : theme === 'dark' ? 'dark' : 'system')}>
          <ViewerIcon name={theme === 'light' ? 'light' : theme === 'dark' ? 'dark' : 'system'} />
        </button>
      {/each}
    </div>
    {#if pdfUrl}<a class="download-control" href={pdfUrl} aria-label="Download PDF" title="Download PDF"><ViewerIcon name="download" /></a>
    {:else}<button class="download-control" type="button" aria-label="Download markdown" title="Download markdown" on:click={onDownload}><ViewerIcon name="download" /></button>{/if}
    <button class="copy-control" type="button" aria-label={copied ? 'Copied' : 'Copy document'} title={copied ? 'Copied' : 'Copy document'} on:click={onCopy}><ViewerIcon name={copied ? 'check' : 'copy'} /></button>
    <slot />
  </nav>
  </div>
  <div class="viewer-progress" role={showProgress ? 'progressbar' : undefined} aria-label={showProgress ? 'Reading progress' : undefined} aria-valuemin={showProgress ? 0 : undefined} aria-valuemax={showProgress ? 100 : undefined} aria-valuenow={showProgress ? progress : undefined}><span style={`width:${progress}%`}></span></div>
</header>

<style>
  .viewer-chrome { position: relative; min-width: 0; padding-top: env(safe-area-inset-top); background: var(--rich-surface); color: var(--rich-text-secondary); }
  .viewer-chrome-inner { box-sizing: border-box; max-width: 1320px; height: 62px; margin: auto; padding: 9px max(40px, env(safe-area-inset-right)) 9px max(40px, env(safe-area-inset-left)); display: flex; align-items: center; gap: 14px; }
  .viewer-title { min-width: 0; flex: 1; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; font-size: 13.5px; line-height: 1.3; font-weight: 500; }
  .viewer-identity { display: flex; align-items: center; gap: 4px; max-width: 12rem; flex: none; font: 500 10.5px/1 var(--rich-font-mono); letter-spacing: .14em; color: var(--rich-accent); border: 1px solid color-mix(in srgb, var(--rich-accent) 35%, transparent); border-radius: 4px; padding: 5px 7px; }
  .viewer-identity > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  nav, .theme-controls { display: flex; align-items: center; flex-shrink: 0; }
  nav { gap: 8px; }
  .theme-controls { gap: 2px; }
  button, a { position: relative; display: inline-grid; place-items: center; width: 34px; height: 34px; padding: 0; border: 1px solid var(--rich-line); border-radius: 7px; background: transparent; color: var(--rich-text-secondary); text-decoration: none; cursor: pointer; }
  button::after, a::after { content: ''; position: absolute; width: 44px; height: 44px; }
  .theme-control { width: 27px; height: 26px; border: 0; border-radius: 6px; }
  .theme-control::after { width: 29px; }
  .theme-control[aria-pressed="true"] { background: var(--rich-control-active); color: var(--rich-text); }
  .copy-control { background: #159fef; border-color: #159fef; color: #061826; }
  button:hover, a:hover { filter: brightness(1.12); }
  button:focus-visible, a:focus-visible { outline: 2px solid var(--rich-accent); outline-offset: 3px; }
  .viewer-progress { height: 1px; background: var(--rich-line); }
  .viewer-progress span { display: block; height: 2px; background: var(--rich-accent); }
  @media (pointer: coarse), (max-width: 600px) { .theme-control, button, a { width: 44px; height: 44px; } .theme-control::after { width: 44px; } }
  @media (max-width: 600px) { .viewer-chrome-inner { padding: 8px 12px; gap: 8px; flex-wrap: wrap; height: auto; min-height: 106px; } .viewer-identity { max-width: 7rem; } .viewer-title { flex-basis: 50%; } nav { width: 100%; gap: 2px; justify-content: flex-end; } }
</style>
