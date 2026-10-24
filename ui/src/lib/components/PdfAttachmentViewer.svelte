<script lang="ts">
  import { onMount } from 'svelte';
  import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist';
  import { base } from '$app/paths';

  let { url }: { url: string } = $props();
  let documentProxy = $state<PDFDocumentProxy | null>(null);
  let pageNumber = $state(1);
  let zoom = $state(1);
  let width = $state(0);
  let viewport = $state<HTMLDivElement | null>(null);
  let canvas = $state<HTMLCanvasElement | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let renderTask: RenderTask | null = null;
  let generation = 0;

  onMount(() => {
    let disposed = false;
    let destroy: (() => Promise<void>) | null = null;
    const observer = new ResizeObserver(([entry]) => {
      width = Math.max(1, Math.floor(entry.contentRect.width));
    });
    if (viewport) observer.observe(viewport);
    void (async () => {
      try {
        const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs');
        const worker = await import('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url');
        if (disposed) return;
        pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
        const task = pdfjs.getDocument({
          url,
          cMapUrl: `${base}/pdfjs/cmaps/`,
          cMapPacked: true,
          standardFontDataUrl: `${base}/pdfjs/standard_fonts/`,
          wasmUrl: `${base}/pdfjs/wasm/`,
        });
        destroy = () => task.destroy();
        const pdf = await task.promise;
        if (!disposed) documentProxy = pdf;
      } catch {
        if (!disposed) error = 'The PDF could not be loaded. It may be encrypted or invalid.';
      } finally { if (!disposed) loading = false; }
    })();
    return () => {
      disposed = true;
      generation += 1;
      observer.disconnect();
      renderTask?.cancel();
      void destroy?.();
      if (canvas) { canvas.width = 0; canvas.height = 0; }
    };
  });

  $effect(() => {
    const pdf = documentProxy;
    const target = canvas;
    const availableWidth = width;
    const number = pageNumber;
    const magnification = zoom;
    if (!pdf || !target || !availableWidth) return;
    const version = ++generation;
    error = null;
    const previous = renderTask;
    previous?.cancel();
    void (async () => {
      try {
        // PDF.js cannot render twice into the same canvas concurrently.
        await previous?.promise.catch(() => {});
        const page = await pdf.getPage(number);
        if (version !== generation) return;
        const base = page.getViewport({ scale: 1 });
        const scale = Math.max(0.01, (availableWidth - 16) / base.width) * magnification;
        const view = page.getViewport({ scale });
        const pixelRatio = Math.min(window.devicePixelRatio || 1, 2,
          Math.sqrt(4_000_000 / (view.width * view.height)),
          4096 / Math.max(view.width, view.height));
        target.width = Math.max(1, Math.floor(view.width * pixelRatio));
        target.height = Math.max(1, Math.floor(view.height * pixelRatio));
        target.style.width = `${view.width}px`;
        target.style.height = `${view.height}px`;
        renderTask = page.render({
          canvas: target,
          viewport: view,
          transform: [pixelRatio, 0, 0, pixelRatio, 0, 0],
        });
        await renderTask.promise;
        page.cleanup();
        if (version === generation) {
          error = null;
          viewport?.scrollTo?.({ top: 0, left: 0 });
        }
      } catch (cause) {
        if (version === generation && !(cause instanceof Error && cause.name === 'RenderingCancelledException')) {
          error = 'This PDF page could not be rendered.';
        }
      }
    })();
    return () => { generation += 1; renderTask?.cancel(); };
  });
</script>

<div class="flex h-full min-h-0 min-w-0 flex-col">
  <div class="flex shrink-0 flex-wrap items-center justify-center gap-2 border-b border-separator bg-chrome p-1 text-sm text-foreground">
    <button class="min-h-11 px-3" disabled={!documentProxy || pageNumber <= 1} onclick={() => { pageNumber -= 1; }}>Previous</button>
    <span aria-live="polite">Page {pageNumber} / {documentProxy?.numPages ?? '…'}</span>
    <button class="min-h-11 px-3" disabled={!documentProxy || pageNumber >= documentProxy.numPages} onclick={() => { pageNumber += 1; }}>Next</button>
    <button class="min-h-11 px-3" aria-label="Zoom out" disabled={zoom <= 1} onclick={() => { zoom = Math.max(1, zoom - 0.25); }}>−</button>
    <button class="min-h-11 px-2" onclick={() => { zoom = 1; }}>Fit width</button>
    <button class="min-h-11 px-3" aria-label="Zoom in" disabled={zoom >= 3} onclick={() => { zoom = Math.min(3, zoom + 0.25); }}>+</button>
  </div>
  <div bind:this={viewport} class="min-h-0 min-w-0 flex-1 overflow-auto overscroll-contain bg-raised text-foreground">
    {#if loading}<p role="status" class="p-4">Loading PDF…</p>{/if}
    {#if error}<p role="alert" class="p-4 text-danger">{error}</p>{/if}
    <canvas bind:this={canvas} class="mx-auto my-2 block bg-white" aria-label={`PDF page ${pageNumber}`}></canvas>
  </div>
</div>
