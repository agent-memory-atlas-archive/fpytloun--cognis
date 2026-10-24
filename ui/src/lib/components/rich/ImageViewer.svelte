<script lang="ts">
  import { createEventDispatcher, onMount, tick } from 'svelte';
  import { observeViewerTheme } from './viewer-theme';
  import { portal } from '$lib/actions/portal';
  import { registerOverlay } from '$lib/stores/overlays';

  export let src: string;
  export let alt = '';
  export let label = 'Image preview';
  export let returnFocus: HTMLElement | null = null;
  let theme = 'dark';
  let family: string | null = null;
  onMount(() => {
    const source = returnFocus ?? document.documentElement;
    const update = () => {
      theme = source.closest('[data-viewer-theme]')?.getAttribute('data-viewer-theme')
        ?? document.documentElement.getAttribute('data-resolved-theme') ?? 'dark';
      family = source.closest('.theme-palette')?.getAttribute('data-theme-family') ?? null;
    };
    update();
    return observeViewerTheme(source, update);
  });
  const dispatch = createEventDispatcher<{ close: void }>();
  let zoomed = false;
  let naturalWidth = 0;
  let canvas: HTMLDivElement;
  let image: HTMLImageElement;
  let scale = 1;
  let fitScale = 1;
  let zoomRevision = 0;
  type Point = { x: number; y: number };
  let mouseOrigin: (Point & { left: number; top: number }) | null = null;

  const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

  function imageAnchor(point: Point): Point {
    const box = image.getBoundingClientRect();
    return { x: clamp((point.x - box.left) / box.width, 0, 1), y: clamp((point.y - box.top) / box.height, 0, 1) };
  }

  async function zoomAt(nextScale: number, anchor: Point, point: Point) {
    const revision = ++zoomRevision;
    zoomed = true;
    scale = clamp(nextScale, fitScale, Math.max(4, fitScale * 4));
    mouseOrigin = null;
    await tick();
    if (revision !== zoomRevision || !image?.isConnected) return;
    const box = image.getBoundingClientRect();
    canvas.scrollLeft += box.left + box.width * anchor.x - point.x;
    canvas.scrollTop += box.top + box.height * anchor.y - point.y;
    mouseOrigin = { ...point, left: canvas.scrollLeft, top: canvas.scrollTop };
  }

  async function resetZoom() {
    ++zoomRevision;
    zoomed = false;
    mouseOrigin = null;
    await tick();
    canvas.scrollTo(0, 0);
  }

  async function toggleZoom(event?: MouseEvent) {
    if (zoomed) return resetZoom();
    const box = image.getBoundingClientRect();
    fitScale = box.width / naturalWidth;
    const point = event?.currentTarget === image.parentElement && event.detail > 0
      ? { x: event.clientX, y: event.clientY }
      : { x: box.left + box.width / 2, y: box.top + box.height / 2 };
    await zoomAt(Math.max(1, fitScale * 2), imageAnchor(point), point);
  }

  function imageGestures(node: HTMLDivElement) {
    const touches = new Map<number, Point>();
    let lastTouch: Point | null = null;
    let tapStart: (Point & { background: boolean }) | null = null;
    let lastTap: (Point & { time: number }) | null = null;
    let moved = false;
    let suppressClick = false;
    let pinch: { distance: number; scale: number; anchor: Point } | null = null;
    const distance = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y);
    const midpoint = (a: Point, b: Point): Point => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });

    function down(event: PointerEvent) {
      if (event.pointerType === 'mouse') { suppressClick = false; return; }
      if (!naturalWidth) return;
      suppressClick = true;
      const point = { x: event.clientX, y: event.clientY };
      touches.set(event.pointerId, point);
      node.setPointerCapture(event.pointerId);
      if (touches.size === 1) {
        tapStart = { ...point, background: event.target === node };
        lastTouch = point;
        moved = false;
        pinch = null;
      } else if (touches.size === 2) {
        const [a, b] = [...touches.values()];
        const center = midpoint(a, b);
        if (!zoomed) fitScale = image.getBoundingClientRect().width / naturalWidth;
        pinch = { distance: Math.max(1, distance(a, b)), scale: zoomed ? scale : fitScale, anchor: imageAnchor(center) };
        moved = true;
        lastTap = null;
      }
    }

    function move(event: PointerEvent) {
      const point = { x: event.clientX, y: event.clientY };
      if (event.pointerType === 'mouse') {
        if (!zoomed || event.buttons) return;
        const box = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        const left = box.left + parseFloat(style.paddingLeft);
        const top = box.top + parseFloat(style.paddingTop);
        const right = box.right - parseFloat(style.paddingRight);
        const bottom = box.bottom - parseFloat(style.paddingBottom);
        mouseOrigin ??= { ...point, left: node.scrollLeft, top: node.scrollTop };
        const pan = (cursor: number, origin: number, scroll: number, min: number, max: number, range: number) =>
          cursor >= origin
            ? scroll + clamp((cursor - origin) / Math.max(1, max - origin), 0, 1) * (range - scroll)
            : scroll * (1 - clamp((origin - cursor) / Math.max(1, origin - min), 0, 1));
        node.scrollLeft = pan(point.x, mouseOrigin.x, mouseOrigin.left, left, right, node.scrollWidth - node.clientWidth);
        node.scrollTop = pan(point.y, mouseOrigin.y, mouseOrigin.top, top, bottom, node.scrollHeight - node.clientHeight);
        return;
      }
      if (!touches.has(event.pointerId)) return;
      touches.set(event.pointerId, point);
      if (tapStart && distance(point, tapStart) > 10) moved = true;
      if (touches.size === 2 && pinch) {
        const [a, b] = [...touches.values()];
        void zoomAt(pinch.scale * distance(a, b) / pinch.distance, pinch.anchor, midpoint(a, b));
      } else if (touches.size === 1 && lastTouch && zoomed) {
        node.scrollLeft += lastTouch.x - point.x;
        node.scrollTop += lastTouch.y - point.y;
        mouseOrigin = null;
      }
      lastTouch = point;
    }

    function up(event: PointerEvent) {
      if (!touches.delete(event.pointerId)) return;
      if (node.hasPointerCapture(event.pointerId)) node.releasePointerCapture(event.pointerId);
      if (touches.size) { lastTouch = [...touches.values()][0]; return; }
      if (event.type !== 'pointercancel' && !moved && tapStart) {
        const now = performance.now();
        if (tapStart.background) dispatch('close');
        else if (lastTap && now - lastTap.time < 350 && distance(tapStart, lastTap) < 30) {
          if (zoomed) void resetZoom();
          else {
            fitScale = image.getBoundingClientRect().width / naturalWidth;
            void zoomAt(Math.max(1, fitScale * 2), imageAnchor(tapStart), tapStart);
          }
          lastTap = null;
        } else lastTap = { ...tapStart, time: now };
      } else lastTap = null;
      if (pinch && zoomed && scale <= fitScale * 1.02) void resetZoom();
      pinch = null;
      lastTouch = null;
      tapStart = null;
    }

    function click(event: MouseEvent) {
      // Touch taps are handled above; suppress the synthesized click so a
      // completed drag/pinch cannot reset zoom or dismiss the backdrop.
      if (suppressClick && event.detail > 0) {
        event.preventDefault();
        event.stopPropagation();
      }
    }
    const wheel = () => { mouseOrigin = null; };
    const resize = () => {
      touches.clear();
      pinch = null;
      tapStart = null;
      lastTap = null;
      if (zoomed) void resetZoom();
    };
    node.addEventListener('pointerdown', down);
    node.addEventListener('pointermove', move);
    node.addEventListener('pointerup', up);
    node.addEventListener('pointercancel', up);
    node.addEventListener('click', click, true);
    node.addEventListener('wheel', wheel, { passive: true });
    window.addEventListener('resize', resize);
    return { destroy() {
      node.removeEventListener('pointerdown', down);
      node.removeEventListener('pointermove', move);
      node.removeEventListener('pointerup', up);
      node.removeEventListener('pointercancel', up);
      node.removeEventListener('click', click, true);
      node.removeEventListener('wheel', wheel);
      window.removeEventListener('resize', resize);
      ++zoomRevision;
    } };
  }

  function mountDialog(dialog: HTMLDialogElement) {
    const previous = returnFocus ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    const overlay = registerOverlay({ kind: 'blocking', blocksChrome: true });
    const closeOnBackdrop = (event: MouseEvent) => {
      if (event.target === dialog || event.target === canvas) dispatch('close');
    };
    dialog.addEventListener('click', closeOnBackdrop);
    dialog.showModal();
    return { destroy() {
      dialog.removeEventListener('click', closeOnBackdrop);
      dialog.close();
      overlay.unregister();
      if (previous?.isConnected) previous.focus();
    } };
  }
</script>

<dialog class="image-viewer" class:theme-palette={Boolean(family)} data-theme-family={family} data-resolved-theme={family ? theme : undefined} data-viewer-theme={theme} aria-label={label} use:portal use:mountDialog
  on:cancel|preventDefault={() => dispatch('close')}>
  <nav class="image-controls" aria-label="Image controls">
    <button class="icon-button" type="button" on:click={toggleZoom}
      aria-label={zoomed ? 'Zoom out' : 'Zoom in'} aria-pressed={zoomed}
      title={zoomed ? 'Fit image to screen' : 'Zoom image'} disabled={!naturalWidth}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true">
        <circle cx="10.5" cy="10.5" r="6.5" />
        <path d="m16 16 4.5 4.5M7.5 10.5h6" />
        {#if !zoomed}<path d="M10.5 7.5v6" />{/if}
      </svg>
    </button>
    <button class="icon-button" type="button" on:click={() => dispatch('close')}
      aria-label="Close image preview" title="Close">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true">
        <path d="m6 6 12 12M18 6 6 18" />
      </svg>
    </button>
  </nav>
  <div class="image-canvas" class:zoomed bind:this={canvas} use:imageGestures>
    <button class="image-toggle" type="button" on:click={toggleZoom}
      aria-label={zoomed ? 'Fit image to screen' : 'Zoom image'} disabled={!naturalWidth}>
      <img {src} {alt} class:zoomed bind:this={image} draggable="false"
        style:width={zoomed && naturalWidth ? `${naturalWidth * scale}px` : undefined}
        on:load={(event) => naturalWidth = (event.currentTarget as HTMLImageElement).naturalWidth} />
    </button>
  </div>
</dialog>

<style>
  .image-viewer {
    position: fixed; inset: 0; width: 100%; height: 100dvh;
    max-width: none; max-height: none; margin: 0; padding: 0;
    border: 0; border-radius: 0; background: transparent; color: #fff;
    overflow: hidden; font-family: var(--rich-font-sans, sans-serif);
  }
  .image-viewer::backdrop { background: rgb(0 0 0 / .9); }
  .image-viewer[data-viewer-theme="dark"] { color-scheme: dark; }
  .image-viewer[data-viewer-theme="light"] { color-scheme: light; color: #0f172a; }
  .image-viewer[data-viewer-theme="light"]::backdrop { background: rgb(246 248 251 / .95); }
  .image-viewer.theme-palette[data-theme-family][data-resolved-theme] { color: rgb(var(--color-foreground)); }
  .image-viewer.theme-palette[data-theme-family][data-resolved-theme]::backdrop { background: rgb(var(--color-canvas) / .95); }
  .image-viewer[data-viewer-theme="light"] .icon-button { background: rgb(255 255 255 / .8); }
  .image-controls {
    position: absolute; z-index: 1;
    top: max(12px, env(safe-area-inset-top)); right: max(16px, env(safe-area-inset-right));
    display: flex; gap: 8px;
  }
  button { padding: 0; border: 0; color: inherit; background: transparent; cursor: pointer; touch-action: manipulation; }
  .icon-button {
    display: grid; place-items: center; width: 44px; height: 44px;
    border-radius: 50%; background: rgb(0 0 0 / .35);
  }
  .icon-button:hover { background: rgb(255 255 255 / .15); }
  .icon-button:disabled { opacity: .4; cursor: default; }
  .icon-button svg { width: 24px; height: 24px; }
  button:focus-visible { outline: 2px solid #39bff5; outline-offset: 2px; }
  .image-canvas {
    box-sizing: border-box; height: 100%; overflow: auto; overscroll-behavior: contain; touch-action: none; scrollbar-width: none;
    padding: max(72px, calc(env(safe-area-inset-top) + 60px)) max(24px, env(safe-area-inset-right)) max(24px, var(--app-safe-area-bottom, 0px)) max(24px, env(safe-area-inset-left));
    display: grid; place-items: center;
  }
  .image-toggle { display: block; max-width: 100%; min-width: 0; cursor: zoom-in; }
  img { display: block; max-width: 100%; max-height: calc(100dvh - 120px - env(safe-area-inset-top) - var(--app-safe-area-bottom, 0px)); object-fit: contain; }
  .image-canvas::-webkit-scrollbar { display: none; }
  .image-canvas.zoomed { display: flex; align-items: safe center; justify-content: safe center; }
  .zoomed .image-toggle { flex: none; width: max-content; max-width: none; cursor: zoom-out; }
  img.zoomed { max-width: none; max-height: none; }
  @media (hover: none) { .image-toggle, .zoomed .image-toggle { cursor: default; } }
  @media (max-width: 600px) {
    .image-canvas { padding-left: max(16px, env(safe-area-inset-left)); padding-right: max(16px, env(safe-area-inset-right)); }
  }
</style>
