<script lang="ts">
  import { afterUpdate, onDestroy, onMount, tick } from 'svelte';
  import { renderInlineMarkdown, renderMarkdown } from '$lib/markdown';
  import { portal } from '$lib/actions/portal';
  import { isTopOverlay, registerOverlay } from '$lib/stores/overlays';
  import { addToast } from '$lib/stores/toasts';
  import {
    blockTitle,
    normalizeRichDeliverable,
    privateDeliverableMediaUrl,
    resolveRichMedia,
    richCanvas,
    richDensity,
    richPresentation,
    type RichMediaUrlFor,
  } from '$lib/rich-deliverable';
  import RichBlockList from './RichBlockList.svelte';
  import RichToc from './RichToc.svelte';
  import RichViewerChrome from './RichViewerChrome.svelte';
  import ViewerIcon from './ViewerIcon.svelte';
  import './rich-publication.css';
  import { loadViewerTheme, observeViewerTheme, viewerTheme } from './viewer-theme';
  import {
    buildCitationRegistry,
    buildTocItems,
    decorateBlocks,
    namespaceTocItems,
    publicationOptions,
  } from './publication';
  import { createPublicationContext } from './publication-context';
  import { allocateRichInstanceNamespace } from './instance-namespace';
  import { namespaceMermaidSvg } from './namespace-svg';

  export let payload: unknown;
  export let content = '';
  export let title = '';
  export let surface: 'embedded' | 'standalone';
  export let compact = false;
  export let collapsedByDefault = false;
  export let standaloneUrl = '';
  export let pdfUrl = '';
  export let shareLinkCallback: (() => Promise<string>) | null = null;
  export let instanceId = '';
  export let mediaUrlFor: RichMediaUrlFor = (mediaKey: string) => instanceId
    ? privateDeliverableMediaUrl(instanceId, mediaKey)
    : '';

  const instanceNamespace = allocateRichInstanceNamespace(instanceId);
  const publicationContext = createPublicationContext();
  $: normalizedPayload = normalizeRichDeliverable(payload);
  $: authorizedMediaUrlFor = (mediaKey: string) =>
    normalizedPayload.media_manifest?.[mediaKey] ? mediaUrlFor(mediaKey) : '';
  $: normalized = resolveRichMedia(normalizedPayload, authorizedMediaUrlFor);
  $: metadata = normalized.metadata;
  $: presentation = richPresentation(metadata);
  $: density = richDensity(metadata, normalized.blocks);
  $: canvas = richCanvas(metadata);
  // Payload-level `title` is only a fallback for payloads authored with the
  // title inline; the host-supplied `title` prop (the deliverable's own
  // stored title/label) always wins when set.
  $: effectiveTitle = title || normalized.title || '';
  $: subtitle = typeof metadata.subtitle === 'string' ? metadata.subtitle : '';
  $: eyebrow = typeof metadata.eyebrow === 'string' ? metadata.eyebrow : '';
  $: badges = Array.isArray(metadata.badges) ? metadata.badges.map(String).filter(Boolean) : [];
  $: options = publicationOptions(metadata, normalized.blocks);
  $: localHeadingItems = buildTocItems(normalized.blocks, 4);
  $: headingItems = namespaceTocItems(localHeadingItems, instanceNamespace);
  $: internalLinkTargets = headingItems.reduce<Record<string, string>>((targets, item) => {
    targets[item.requestedAnchor] ??= item.anchor;
    return targets;
  }, {});
  $: tocItems = [
    ...(heroOwnsIdentity && !headingItems.some(item => item.label === 'Overview') ? [{ anchor: `${instanceNamespace}-overview`, requestedAnchor: 'overview', label: 'Overview', level: 2 as const, block: normalized.blocks[0] }] : []),
    ...headingItems.filter((item) => item.level <= options.tocDepth).map(item => ({
      ...item,
      label: item.block.type === 'section' && typeof item.block.eyebrow === 'string' && /^\d+$/.test(item.block.eyebrow)
        ? `${Number(item.block.eyebrow)}  ${item.label}` : item.label,
    })),
  ];
  $: decoratedBlocks = decorateBlocks(normalized.blocks, headingItems, options, instanceNamespace);
  $: heroTitle = normalized.blocks[0]?.type === 'hero' ? blockTitle(normalized.blocks[0]) : '';
  $: heroOwnsIdentity = Boolean(heroTitle);
  // Dashboard documents use their first section header as the presentation
  // title. Keep the host toolbar for actions, but do not duplicate that title
  // above the authored dashboard canvas.
  $: dashboardSectionOwnsIdentity = presentation === 'dashboard'
    && normalized.blocks[0]?.type === 'section_header'
    && Boolean(blockTitle(normalized.blocks[0]));
  $: payloadOwnsIdentity = heroOwnsIdentity || dashboardSectionOwnsIdentity;
  $: documentBlocks = decoratedBlocks.map((block, index) => index === 0
    && ((block.type === 'hero' && heroOwnsIdentity) || (block.type === 'section_header' && dashboardSectionOwnsIdentity))
    ? { ...block, __document_h1: true, ...(heroOwnsIdentity ? { __publication_anchor: `${instanceNamespace}-overview` } : {}) }
    : block);
  $: publicationContext.set(buildCitationRegistry(normalized.blocks, normalized.sources, instanceNamespace));
  $: showToc = options.showToc;
  let fullOpen = false;
  let inlineExpanded = !collapsedByDefault;
  let tocOpen = false;
  let tocChosen = false;
  let readingProgress = 0;
  let copied = false;
  let copyError = '';
  let copyResetTimer: ReturnType<typeof setTimeout> | null = null;
  let systemDark = true;
  $: resolvedViewerTheme = $viewerTheme === 'system' ? (systemDark ? 'dark' : 'light') : $viewerTheme;
  let shareCopied = false;
  let shareError = '';
  let shareCopyResetTimer: ReturnType<typeof setTimeout> | null = null;
  let root: HTMLDivElement;
  let modalPanel: HTMLDivElement;
  let closeButton: HTMLButtonElement;
  let lastFocusedElement: HTMLElement | null = null;
  let overlayId: string | null = null;
  let unregisterOverlay: (() => void) | null = null;
  let mermaidRenderQueued = false;
  let inlineTocWide = false;
  let rootResizeObserver: ResizeObserver | null = null;
  let collapseIdentity = '';

  $: {
    const nextCollapseIdentity = `${instanceId}\u0000${title}`;
    if (nextCollapseIdentity !== collapseIdentity) {
      collapseIdentity = nextCollapseIdentity;
      inlineExpanded = !collapsedByDefault;
      tocOpen = false;
      tocChosen = false;
    }
  }

  function replaceFragment(fragment: string) {
    history.replaceState(history.state, '', fragment);
  }

  function navigateToc(item: (typeof tocItems)[number]) {
    const visibleRoot = fullOpen ? modalPanel : root;
    const target = visibleRoot?.querySelector<HTMLElement>(`#${item.anchor}`);
    target?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    target?.focus?.({ preventScroll: true });
    requestAnimationFrame(() => target?.focus?.({ preventScroll: true }));
    replaceFragment(`#${item.anchor}`);
  }

  function openContextualToc() {
    if (showToc) { tocChosen = true; tocOpen = true; }
  }

  function closeToc() { tocChosen = true; tocOpen = false; }

  function downloadMarkdown() {
    const url = URL.createObjectURL(new Blob([content || JSON.stringify(normalized, null, 2)], { type: 'text/markdown;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `${(effectiveTitle || 'deliverable').replace(/[^a-z0-9_-]+/gi, '-').slice(0, 100)}.md`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function toggleInlineDocument() {
    inlineExpanded = !inlineExpanded;
    if (!inlineExpanded) tocOpen = false;
  }

  /**
   * The full-view modal is portaled to `document.body` (see `use:portal`
   * below) so it can escape the `isolation: isolate` stacking context on
   * `.rich-deliverable`. That means it is no longer a DOM descendant of
   * `root` once open, so any logic that used to find its content via
   * `root.querySelectorAll(...)` needs to also scan `modalPanel`.
   */
  function scopedRoots(): HTMLDivElement[] {
    return [root, modalPanel].filter((el): el is HTMLDivElement => Boolean(el));
  }

  function rewriteInternalLinks() {
    for (const scope of scopedRoots()) {
      for (const link of scope.querySelectorAll<HTMLAnchorElement>('a[href^="#"]')) {
        const fragment = link.getAttribute('href')?.slice(1) ?? '';
        const target = internalLinkTargets[fragment];
        if (target) link.setAttribute('href', `#${target}`);
      }
    }
  }

  function handleRootClick(event: MouseEvent) {
    const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>('a[href^="#"]') : null;
    if (!link) return;
    const scope = scopedRoots().find((candidate) => candidate.contains(link));
    if (!scope) return;
    const target = scope.querySelector<HTMLElement>(link.getAttribute('href') ?? '');
    if (!target) return;
    event.preventDefault();
    target.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    target.focus({ preventScroll: true });
    replaceFragment(link.getAttribute('href') ?? '');
  }

  /** Mirrors `root`'s click-to-navigate handling for the portaled modal
   * panel, since it is no longer a descendant of `root` once open. */
  function bindPanelInteractions(node: HTMLDivElement): { destroy(): void } {
    node.addEventListener('click', handleRootClick, true);
    const stopThemeObservation = observeViewerTheme(node, refreshMermaidTheme);
    return {
      destroy(): void {
        node.removeEventListener('click', handleRootClick, true);
        stopThemeObservation();
      },
    };
  }

  async function copyFallback() {
    copied = false;
    copyError = '';
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(content || JSON.stringify(normalized, null, 2));
      copied = true;
      if (copyResetTimer) clearTimeout(copyResetTimer);
      copyResetTimer = setTimeout(() => copied = false, 1500);
    } catch {
      copyError = 'Could not copy document. Check clipboard permissions and try again.';
    }
  }

  async function copyShareLink() {
    if (!shareLinkCallback) return;
    shareError = '';
    try {
      const url = await shareLinkCallback();
      await navigator.clipboard.writeText(url);
      shareCopied = true;
      if (shareCopyResetTimer) clearTimeout(shareCopyResetTimer);
      shareCopyResetTimer = setTimeout(() => {
        shareCopied = false;
        shareCopyResetTimer = null;
      }, 3_000);
      addToast('Copied into clipboard', 'success');
    } catch (err) {
      shareError = err instanceof Error ? err.message : 'Share link failed';
    }
  }

  /** Resolve live `--rich-*` tokens into a Mermaid themeVariables object so
   * diagrams follow the resolved light/dark theme instead of always
   * rendering with hardcoded dark colors (Mermaid draws its own inline SVG
   * styles and cannot read CSS custom properties itself). */
  function resolveMermaidTheme(el: Element | undefined) {
    const fallbackDark = {
      background: '#020617',
      primaryColor: '#0f172a',
      primaryTextColor: '#e2e8f0',
      primaryBorderColor: '#38bdf8',
      lineColor: '#67e8f9',
      secondaryColor: '#082f49',
      secondaryTextColor: '#e0f2fe',
      secondaryBorderColor: '#0ea5e9',
      tertiaryColor: '#111827',
      tertiaryTextColor: '#e5e7eb',
      tertiaryBorderColor: '#334155',
      noteBkgColor: '#0f172a',
      noteTextColor: '#e2e8f0',
      noteBorderColor: '#38bdf8',
      clusterBkg: '#020617',
      clusterBorder: '#1e293b',
      edgeLabelBackground: '#020617',
    };
    if (typeof window === 'undefined' || !el) return { darkMode: true, themeVariables: fallbackDark };
    const style = getComputedStyle(el);
    const surface = style.getPropertyValue('--rich-surface').trim();
    const surfaceRaised = style.getPropertyValue('--rich-surface-raised').trim();
    const text = style.getPropertyValue('--rich-text').trim();
    const textSecondary = style.getPropertyValue('--rich-text-secondary').trim();
    const accent = style.getPropertyValue('--rich-accent').trim();
    const accentSoft = style.getPropertyValue('--rich-accent-soft').trim();
    const line = style.getPropertyValue('--rich-line').trim();
    if (!surface || !text || !accent) return { darkMode: true, themeVariables: fallbackDark };
    // Deliverables default to dark regardless of OS preference (see
    // rich-blocks.css); only an explicit data-resolved-theme="light"
    // (reserved for a future app-wide theme switch) should render a light
    // mermaid diagram. No matchMedia fallback here, or diagrams would
    // follow the OS light preference while the rest of the deliverable
    // stayed dark.
    const isLight = el.closest('[data-viewer-theme]')?.getAttribute('data-viewer-theme') === 'light'
      || (!el.closest('[data-viewer-theme]') && document.documentElement.getAttribute('data-resolved-theme') === 'light');
    return {
      darkMode: isLight ? false : true,
      themeVariables: {
        background: surface,
        primaryColor: surfaceRaised,
        primaryTextColor: text,
        primaryBorderColor: accent,
        lineColor: accentSoft,
        secondaryColor: surfaceRaised,
        secondaryTextColor: textSecondary,
        secondaryBorderColor: accent,
        tertiaryColor: surface,
        tertiaryTextColor: textSecondary,
        tertiaryBorderColor: line,
        noteBkgColor: surfaceRaised,
        noteTextColor: textSecondary,
        noteBorderColor: accent,
        clusterBkg: surface,
        clusterBorder: line,
        edgeLabelBackground: surface,
      },
    };
  }

  async function renderMermaidFallbacks() {
    await tick();
    const nodes = scopedRoots().flatMap((scope) => Array.from(scope.querySelectorAll('pre[data-mermaid-source]')));
    if (nodes.length === 0) return;
    try {
      const mermaid = (await import('mermaid')).default;
      const resolvedTheme = resolveMermaidTheme(fullOpen ? modalPanel : root);
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: 'base',
        darkMode: resolvedTheme.darkMode,
        themeVariables: {
          ...resolvedTheme.themeVariables,
          fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
        },
      });
      for (const [index, node] of nodes.entries()) {
        const source = node.textContent ?? '';
        try {
          const renderId = (node as HTMLElement).dataset.mermaidId || `${instanceNamespace}-mermaid-${index}`;
          const result = await mermaid.render(renderId, source);
          const wrapper = document.createElement('div');
          wrapper.className = 'rich-mermaid';
          wrapper.dataset.mermaidSource = source;
          wrapper.dataset.mermaidId = renderId;
          wrapper.innerHTML = namespaceMermaidSvg(result.svg, renderId);
          node.replaceWith(wrapper);
        } catch {
          // Keep escaped source fallback.
        }
      }
    } catch {
      // Mermaid is optional at runtime; source fallback remains usable.
    }
  }

  function scheduleMermaidRender() {
    if (mermaidRenderQueued) return;
    mermaidRenderQueued = true;
    queueMicrotask(async () => {
      mermaidRenderQueued = false;
      await renderMermaidFallbacks();
    });
  }

  function refreshMermaidTheme() {
    for (const scope of scopedRoots()) {
      for (const wrapper of scope.querySelectorAll<HTMLElement>('.rich-mermaid[data-mermaid-source]')) {
        const source = document.createElement('pre');
        source.dataset.mermaidSource = wrapper.dataset.mermaidSource;
        source.dataset.mermaidId = wrapper.dataset.mermaidId;
        source.textContent = wrapper.dataset.mermaidSource ?? '';
        wrapper.replaceWith(source);
      }
    }
    scheduleMermaidRender();
  }

  onMount(() => {
    loadViewerTheme();
    const query = window.matchMedia?.('(prefers-color-scheme: dark)');
    systemDark = query?.matches ?? true;
    const change = (event: MediaQueryListEvent) => systemDark = event.matches;
    query?.addEventListener('change', change);
    const stopThemeObservation = observeViewerTheme(root, refreshMermaidTheme);
    root.addEventListener('click', handleRootClick, true);
    root.addEventListener('rich-toc-request', openContextualToc);
    rewriteInternalLinks();
    scheduleMermaidRender();
    if (typeof ResizeObserver !== 'undefined') {
      rootResizeObserver = new ResizeObserver(([entry]) => {
        inlineTocWide = (entry?.contentRect.width ?? 0) >= 960;
        if (!tocChosen) tocOpen = inlineTocWide;
      });
      rootResizeObserver.observe(root);
    }
    return () => {
      query?.removeEventListener('change', change);
      stopThemeObservation();
    };
  });
  afterUpdate(() => {
    rewriteInternalLinks();
    scheduleMermaidRender();
  });
  onDestroy(() => {
    root?.removeEventListener('click', handleRootClick, true);
    root?.removeEventListener('rich-toc-request', openContextualToc);
    unregisterOverlay?.();
    rootResizeObserver?.disconnect();
    if (shareCopyResetTimer) clearTimeout(shareCopyResetTimer);
    if (copyResetTimer) clearTimeout(copyResetTimer);
  });
  $: if (fullOpen) scheduleMermaidRender();

  $: if (fullOpen && !unregisterOverlay) {
    const handle = registerOverlay({ kind: 'fullscreen', blocksChrome: true });
    overlayId = handle.id;
    unregisterOverlay = handle.unregister;
  }

  $: if (!fullOpen && unregisterOverlay) {
    unregisterOverlay();
    unregisterOverlay = null;
    overlayId = null;
  }

  async function openFullView() {
    lastFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    tocOpen = window.innerWidth >= 960;
    fullOpen = true;
    await tick();
    closeButton?.focus();
  }

  async function closeFullView() {
    fullOpen = false;
    const restoreTarget = lastFocusedElement;
    lastFocusedElement = null;
    await tick();
    if (restoreTarget?.isConnected) restoreTarget.focus({ preventScroll: true });
  }

  function focusableModalElements(): HTMLElement[] {
    const nodes = modalPanel?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    ) ?? [];
    const visible = Array.from(nodes).filter((node) => node.offsetParent !== null || node === closeButton);
    // Keep the dialog panel in the focus cycle for single-action modals.
    return modalPanel && modalPanel.tabIndex >= 0 ? [modalPanel, ...visible] : visible;
  }

  function handleKeydown(event: KeyboardEvent) {
    if (!fullOpen || !isTopOverlay(overlayId)) return;
    event.stopPropagation();
    if (event.key === 'Escape') {
      closeFullView();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = focusableModalElements();
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
</script>

<div
  bind:this={root}
  class:compact
  class:embedded={surface === 'embedded'}
  class="rich-deliverable"
  class:pulse={presentation === 'pulse'}
  class:dashboard={presentation === 'dashboard'}
  data-presentation={presentation}
  data-rich-density={density}
  data-rich-canvas={canvas}
  data-rich-instance={instanceNamespace}
  data-has-contextual-toc={showToc ? 'true' : undefined}
  data-inline-toc-layout={inlineTocWide ? 'sidebar' : 'drawer'}
  data-testid="rich-deliverable"
  data-viewer-theme={surface === 'standalone' ? resolvedViewerTheme : undefined}
>
  {#if surface === 'standalone'}
    <RichViewerChrome title={payloadOwnsIdentity ? blockTitle(normalized.blocks[0]) : effectiveTitle} identity={metadata.viewer_identity} {pdfUrl} {copied} onCopy={copyFallback} onDownload={downloadMarkdown} progress={readingProgress} showProgress={showToc}>
      {#if showToc && (!inlineTocWide || !tocOpen)}<button class="viewer-extra-control" type="button" aria-label="Open table of contents" aria-expanded={tocOpen} on:click={openContextualToc}><ViewerIcon name="contents" /></button>{/if}
      {#if shareLinkCallback}<button class="viewer-extra-control" type="button" title={shareCopied ? 'Copied into clipboard' : 'Copy share link'} aria-label={shareCopied ? 'Share link copied' : 'Copy share link'} on:click={copyShareLink}><span data-testid={shareCopied ? 'rich-share-copied-icon' : 'rich-share-icon'}><ViewerIcon name={shareCopied ? 'check' : 'share'} /></span></button>{/if}
    </RichViewerChrome>
  {/if}

  <header class="rich-toolbar" class:actions-only={payloadOwnsIdentity && inlineExpanded} data-testid="rich-deliverable-toolbar">
    {#if !payloadOwnsIdentity || !inlineExpanded}
    <div>
      {#if eyebrow}<span class="rich-eyebrow">{@html renderInlineMarkdown(eyebrow)}</span>{/if}
      <h1>{@html renderInlineMarkdown(effectiveTitle || 'Deliverable')}</h1>
      {#if subtitle}<p>{@html renderInlineMarkdown(subtitle)}</p>{/if}
      {#if badges.length > 0}
        <div class="rich-badges">{#each badges as badge}<span>{@html renderInlineMarkdown(badge)}</span>{/each}</div>
      {/if}
    </div>
    {/if}
    {#if surface === 'embedded'}
    <nav class="rich-actions" aria-label="Document actions">
      {#if collapsedByDefault}
        <button
          type="button"
          aria-label={inlineExpanded ? 'Collapse document' : 'Expand document'}
          title={inlineExpanded ? 'Collapse document' : 'Expand document'}
          aria-expanded={inlineExpanded}
          aria-controls={`${instanceNamespace}-inline-document`}
          on:click={toggleInlineDocument}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d={inlineExpanded ? 'm6 15 6-6 6 6' : 'm6 9 6 6 6-6'} /></svg>
        </button>
      {/if}
      {#if showToc && (!inlineTocWide || !tocOpen)}
        <button class="rich-toc-action" type="button" aria-label="Open table of contents" title="Open table of contents" aria-expanded={tocOpen} on:click={openContextualToc}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h2m3 0h11M4 12h2m3 0h11M4 18h2m3 0h11" /></svg>
        </button>
      {/if}
      <!-- "Open full view" and "Open standalone page" are only meaningful
           from embedded chat -- opening either from the standalone page
           itself would just reopen the same page/a fullscreen copy of the
           page you're already looking at. -->
      {#if surface === 'embedded'}
        <button type="button" aria-label="Open full view" title="Open full view" on:click={openFullView}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5" /></svg></button>
        {#if standaloneUrl}<a href={standaloneUrl} target="_blank" rel="noreferrer" aria-label="Open standalone page" title="Open standalone page"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6M20 4 11 13M10 6H5a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-5" /></svg></a>{/if}
      {/if}
      {#if pdfUrl}<a href={pdfUrl} aria-label="Download PDF" title="Download PDF"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m-4-4 4 4 4-4M5 20h14" /></svg></a>{/if}
      {#if shareLinkCallback}
        <button
          class:rich-action-copied={shareCopied}
          type="button"
          aria-label={shareCopied ? 'Share link copied' : 'Copy share link'}
          title={shareCopied ? 'Copied into clipboard' : 'Copy share link'}
          on:click={copyShareLink}
        >
          {#if shareCopied}
            <svg data-testid="rich-share-copied-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="12" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h2" /></svg>
          {:else}
            <svg data-testid="rich-share-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="18" cy="5" r="2.5" /><circle cx="6" cy="12" r="2.5" /><circle cx="18" cy="19" r="2.5" /><path d="m8.2 10.8 7.6-4.5M8.2 13.2l7.6 4.5" /></svg>
          {/if}
        </button>
      {/if}
      <button type="button" aria-label={copied ? 'Copied' : 'Copy document'} title="Copy document" on:click={copyFallback}><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="12" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h2" /></svg></button>
    </nav>
    {/if}
  </header>
  {#if shareError}<p class="rich-action-error">{shareError}</p>{/if}
  {#if copyError}<p class="rich-action-error" role="alert">{copyError}</p>{/if}

  {#if !fullOpen && inlineExpanded}
  <div
    id={`${instanceNamespace}-inline-document`}
    class:has-toc={showToc && tocOpen}
    class:inline-toc-sidebar={showToc && inlineTocWide && tocOpen}
    class="rich-document rich-inline-document"
    data-testid="rich-deliverable-inline-document"
  >
    {#if showToc}
      <RichToc
        items={tocItems}
        onNavigate={navigateToc}
        bind:open={tocOpen}
        onClose={closeToc}
        bind:progress={readingProgress}
        layout={inlineTocWide ? 'sidebar' : 'drawer'}
        visible={inlineTocWide ? tocOpen : true}
        dismissibleSidebar={true}
        theme={surface === 'standalone' ? resolvedViewerTheme : undefined}
        documentRoot={() => root}
      />
    {/if}

    <div class="rich-body" data-testid="rich-deliverable-body">
      {#if normalized.blocks.length > 0}
          <RichBlockList blocks={documentBlocks} sources={normalized.sources} mediaUrlFor={authorizedMediaUrlFor} />
      {:else}
        <div class="rich-fallback">{@html renderMarkdown(content)}</div>
      {/if}
    </div>
  </div>
  {/if}

  {#if fullOpen}
    <div
      class="rich-full"
      class:pulse={presentation === 'pulse'}
      class:dashboard={presentation === 'dashboard'}
      use:portal
      role="dialog"
      aria-modal="true"
      tabindex="-1"
      aria-label={effectiveTitle || 'Document full view'}
      data-testid="rich-deliverable-full-view"
      data-presentation={presentation}
      data-rich-density={density}
      data-rich-canvas={canvas}
      data-viewer-theme={resolvedViewerTheme}
      on:keydown|capture={handleKeydown}
    >
      <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
      <div class="rich-full-panel" bind:this={modalPanel} tabindex="0" use:bindPanelInteractions>
         <RichViewerChrome title={payloadOwnsIdentity ? blockTitle(normalized.blocks[0]) : effectiveTitle} identity={metadata.viewer_identity} {pdfUrl} {copied} onCopy={copyFallback} onDownload={downloadMarkdown} progress={readingProgress} showProgress={showToc}>
           {#if shareLinkCallback}<button class="viewer-extra-control" type="button" aria-label={shareCopied ? 'Share link copied' : 'Copy share link'} on:click={copyShareLink}><ViewerIcon name="share" /></button>{/if}
           {#if showToc && !tocOpen}
             <button class="viewer-extra-control" type="button" aria-label="Open table of contents" title="Open table of contents" aria-expanded={tocOpen} on:click={openContextualToc}><ViewerIcon name="contents" /></button>
           {/if}
           <button class="viewer-extra-control" bind:this={closeButton} type="button" aria-label="Close" title="Close full view" on:click={closeFullView}><ViewerIcon name="close" /></button>
         </RichViewerChrome>
         {#if copyError}<p class="rich-action-error" role="alert">{copyError}</p>{/if}
        <div class="rich-full-body">
              <div class:has-toc={showToc && tocOpen} class="rich-document">
               {#if showToc}
                  <RichToc items={tocItems} onNavigate={navigateToc} bind:open={tocOpen} bind:progress={readingProgress} onClose={closeToc} layout="auto" visible={tocOpen} dismissibleSidebar={true} theme={resolvedViewerTheme} documentRoot={() => modalPanel} />
                {/if}

            <div class="rich-body">
              {#if !payloadOwnsIdentity}<h1 class="document-title">{effectiveTitle || 'Deliverable'}</h1>{#if subtitle}<p class="document-lede">{subtitle}</p>{/if}{/if}
              {#if normalized.blocks.length > 0}
                 <RichBlockList blocks={documentBlocks} sources={normalized.sources} mediaUrlFor={authorizedMediaUrlFor} />
              {:else}
                <div class="rich-fallback">{@html renderMarkdown(content)}</div>
              {/if}
            </div>
          </div>
        </div>
      </div>
    </div>
  {/if}
</div>

<style>
  .rich-deliverable {
    position: relative;
    isolation: isolate;
    container: rich-inline / inline-size;
    width: 100%;
    min-width: 0;
    max-width: 100%;
    overflow: clip;
    border: 1px solid var(--rich-line);
    border-radius: .35rem;
    background: var(--rich-surface);
  }

  .rich-deliverable.compact {
    border-radius: 1.25rem;
  }

  .rich-deliverable.embedded {
    border-radius: .35rem;
  }

  .rich-deliverable.pulse {
    border-color: rgb(148 163 184 / 0.18);
    border-radius: .35rem;
    background: var(--rich-surface);
    box-shadow: 0 18px 55px rgb(2 6 23 / .2);
  }

  .rich-deliverable.pulse .rich-toolbar {
    min-height: 2.9rem;
    padding: .35rem .65rem;
    border-bottom-color: rgb(148 163 184 / .2);
    background: transparent;
  }

  .rich-deliverable.pulse .rich-toolbar.actions-only {
    padding-block: .25rem;
  }

  .rich-deliverable.pulse .rich-actions button,
  .rich-deliverable.pulse .rich-actions a {
    width: 2.25rem;
    min-width: 2.25rem;
    height: 2.25rem;
    border-radius: 999px;
    background: transparent;
  }


  /* .rich-full is portaled to document.body (see use:portal) to escape the
     isolated stacking context above, so it carries its own .pulse class
     (set alongside .rich-deliverable.pulse) instead of relying on
     .rich-deliverable as an ancestor -- every pulse rule above that visually
     matters for full-view needs an explicit `.rich-full.pulse` companion,
     since `.rich-deliverable.pulse ...` selectors never match inside the
     portaled `.rich-full` tree. `.rich-orb`/`.rich-toolbar`/`.rich-actions`
     don't need one: those elements only exist in the non-full-view
     document, not inside `.rich-full`'s own header/body markup. `.rich-body`
     does: the same `.rich-body` class is reused inside full-view's
     `.rich-full-body`, and previously fell back to the generic full-width
     layout there instead of pulse's narrower editorial column, which was
     the most visible source of full-view looking different from the
     standalone page for Pulse presentations. */
  .rich-full.pulse .rich-full-panel {
    background: var(--rich-surface);
  }


  /* Dashboard presentation: flat, editorial, and dense -- restrained
     shadows/gradients (no ambient orbs, a plain surface instead of the
     default's layered gradient shell), strong section dividers (inherited
     from `--rich-line` borders already used throughout), and tabular
     numeric treatment (see `.rich-deliverable.dashboard :is(strong, .rich-metric strong)`
     rules in rich-blocks.css). Kept minimal here: only the outer shell and
     orb suppression are dashboard-specific chrome; everything else reuses
     the same generic primitives every other presentation shares. */
   .rich-deliverable.dashboard {
     border-color: transparent;
     border-radius: 0;
      background: var(--rich-surface);
     box-shadow: none;
   }

   .rich-full.dashboard .rich-full-panel {
      background: var(--rich-surface);
     box-shadow: none;
   }


   .rich-deliverable.dashboard .rich-toolbar {
     min-height: 2.25rem;
     padding: .3rem .55rem;
     border-bottom-color: color-mix(in srgb, var(--rich-line) 72%, transparent);
     background: transparent;
     backdrop-filter: none;
   }

   .rich-deliverable.dashboard .rich-toolbar.actions-only {
     padding-block: .2rem;
   }

   .rich-deliverable.dashboard .rich-actions {
     gap: .3rem;
   }

   .rich-deliverable.dashboard .rich-actions button,
   .rich-deliverable.dashboard .rich-actions a {
     width: 2rem;
     min-width: 2rem;
     height: 2rem;
     border-radius: .45rem;
     border-color: color-mix(in srgb, var(--rich-line) 75%, transparent);
     background: transparent;
   }


  /* Constrain reading content, never the full-view canvas. Embedded width
     remains owned by the chat host. */
  .rich-deliverable[data-rich-canvas='wide']:not(.embedded) .rich-body {
    width: min(100%, 104rem);
    margin: 0 auto;
  }

  /* Deliverables default to dark regardless of OS preference until Cognis
     ships app-wide theming (no per-deliverable toggle exists). This used to
     hardcode a light pulse background/color purely from
     `prefers-color-scheme: light`, with no `data-resolved-theme` check at
     all -- so pulse rendered light on any light-OS machine with no way
     back to dark. Removed; a future explicit `data-resolved-theme="light"`
     variant can be added here when app-wide theming lands. */

  .rich-toolbar {
    display: flex;
    gap: 1rem;
    align-items: flex-start;
    justify-content: space-between;
    padding: clamp(1.1rem, 2.5vw, 1.7rem);
    border-bottom: 1px solid var(--rich-line);
    background: var(--rich-surface);
  }

  .rich-toolbar.actions-only {
    justify-content: flex-end;
    padding-block: 0.65rem;
  }

  .rich-toolbar > div {
    min-width: 0;
  }

  .rich-deliverable.embedded .rich-toolbar {
    padding: clamp(0.85rem, 1.8vw, 1.15rem);
  }

  .rich-toolbar h1 {
    display: block;
    margin: 0.15rem 0 0;
    color: var(--rich-text);
    font-size: clamp(2rem, 4vw, 3.6rem);
    letter-spacing: -0.045em;
    line-height: 1.05;
  }

  .rich-deliverable.embedded .rich-toolbar h1 {
    font-size: clamp(1.08rem, 2.1vw, 1.48rem);
    line-height: 1.14;
  }

  .rich-toolbar p {
    max-width: 54rem;
    margin: 0.55rem 0 0;
    color: var(--rich-text-secondary);
    line-height: 1.6;
  }

  .rich-deliverable.embedded .rich-toolbar p {
    margin-top: 0.42rem;
    line-height: 1.5;
  }

  .rich-eyebrow {
    color: var(--rich-accent-soft);
    font-size: 0.72rem;
    font-weight: 850;
    letter-spacing: 0.18em;
    text-transform: uppercase;
  }

  .rich-badges {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    margin-top: 0.85rem;
  }

  .rich-deliverable.embedded .rich-badges {
    margin-top: 0.6rem;
  }

  .rich-badges span {
    border: 1px solid color-mix(in srgb, var(--rich-accent) 22%, transparent);
    border-radius: 999px;
    background: color-mix(in srgb, var(--rich-accent) 10%, var(--rich-surface-wash));
    color: var(--rich-accent-soft);
    padding: 0.28rem 0.58rem;
    font-size: 0.74rem;
    font-weight: 750;
  }

  nav {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 0.5rem;
    min-width: 0;
    max-width: 100%;
  }

  .rich-actions svg,
  .rich-full svg {
    width: 1.2rem;
    height: 1.2rem;
    fill: none;
    stroke: currentColor;
    stroke-linecap: round;
    stroke-linejoin: round;
    stroke-width: 1.8;
  }

  .rich-actions button,
  .rich-actions a,
  .rich-full button,
  .rich-deliverable:not(.embedded) button {
    width: 2.75rem;
    min-width: 2.75rem;
    height: 2.75rem;
    justify-content: center;
    padding: 0;
  }

  /* TOC affordance: a sticky sidebar only on very large/wide screens
     (>=1440px); everything else, including tablets and typical desktop
     windows, uses the hamburger-triggered drawer. */
  .rich-toc-action {
    display: inline-flex;
  }


  button,
  nav a {
    display: inline-flex;
    align-items: center;
    border: 1px solid var(--rich-line);
    border-radius: 0.85rem;
    background: color-mix(in srgb, var(--rich-surface-raised) 88%, transparent);
    color: var(--rich-text-secondary);
    padding: 0.48rem 0.72rem;
    font-size: 0.82rem;
    font-weight: 700;
    text-decoration: none;
    transition: border-color 150ms ease, background 150ms ease, transform 150ms ease;
  }

  button:hover,
  nav a:hover {
    border-color: color-mix(in srgb, var(--rich-accent) 45%, transparent);
    background: color-mix(in srgb, var(--rich-accent) 14%, var(--rich-surface-raised));
    color: var(--rich-text);
    transform: translateY(-1px);
  }

  .rich-action-copied svg {
    animation: rich-action-icon-enter 180ms ease-out;
  }

  @keyframes rich-action-icon-enter {
    from {
      opacity: 0;
      transform: scale(0.72);
    }
    to {
      opacity: 1;
      transform: scale(1);
    }
  }

  .rich-action-error {
    margin: 0;
    border-bottom: 1px solid var(--rich-line);
    color: var(--rich-tone-danger-fg);
    padding: 0.65rem 1rem;
    font-size: 0.82rem;
  }

  .rich-document {
    display: block;
    min-width: 0;
    max-width: 100%;
  }

  /* Inline TOC layout follows this component's measured container, not the
     viewport. Narrow embeddings use the drawer and one readable body column. */
  .rich-inline-document.inline-toc-sidebar {
    display: grid;
    grid-template-columns: minmax(11rem, 14rem) minmax(0, 1fr);
    gap: clamp(0.85rem, 2vw, 1.25rem);
    align-items: start;
    padding: clamp(0.85rem, 2vw, 1.2rem);
  }

  .rich-inline-document.inline-toc-sidebar .rich-body {
    min-width: 0;
    padding: 0;
  }

  .rich-body {
    min-width: 0;
    max-width: 100%;
    padding: clamp(1rem, 2.5vw, 1.7rem);
  }

  .rich-deliverable.embedded .rich-body {
    padding: clamp(0.85rem, 1.9vw, 1.2rem);
  }

  .rich-fallback {
    color: var(--rich-text-secondary);
    line-height: 1.7;
  }

  .rich-full {
    position: fixed;
    inset: 0;
    z-index: 2147483000;
    display: grid;
    place-items: start center;
    overflow: auto;
    padding: 0;
    background: var(--rich-surface);
  }

  .rich-full-panel {
    width: 100%;
    min-width: 0;
    min-height: 100vh;
    min-height: 100dvh;
    background: var(--rich-surface);
  }

  .rich-full-body {
    padding: clamp(1rem, 3vw, 2rem);
  }

  .rich-full-body .rich-document.has-toc {
    padding: 0;
  }

  /* Fullscreen keeps the established viewport-driven TOC contract because
     its portal is no longer inside the inline container. Keep this threshold
     aligned with RichToc's automatic sidebar mode. */
  @media (min-width: 1024px) {
    .rich-full-body .rich-document.has-toc {
      display: grid;
      grid-template-columns: minmax(11rem, 14rem) minmax(0, 1fr);
      gap: clamp(0.85rem, 2vw, 1.25rem);
      align-items: start;
    }

    .rich-full-body .rich-document.has-toc .rich-body {
      min-width: 0;
      padding: 0;
    }
  }

  @media (max-width: 760px) {
    .rich-deliverable {
      border-radius: 1rem;
    }

    .rich-toolbar {
      flex-direction: column;
      gap: 0.8rem;
      padding: 0.9rem;
    }

    .rich-toolbar.actions-only {
      flex-direction: row;
      padding-block: .45rem;
    }

    .rich-toolbar h1 {
      font-size: clamp(1.2rem, 6.5vw, 1.65rem);
      line-height: 1.16;
      overflow-wrap: anywhere;
    }

    .rich-toolbar p {
      font-size: 0.9rem;
      line-height: 1.5;
    }

    .rich-eyebrow {
      font-size: 0.68rem;
    }

    nav {
      justify-content: flex-start;
      min-width: 0;
      width: 100%;
    }

    button,
    nav a {
      border-radius: 0.8rem;
      padding: 0.45rem 0.62rem;
      font-size: 0.74rem;
      white-space: normal;
    }

    .rich-body,
    .rich-full-body {
      padding: 0.75rem;
    }

    .rich-full {
      padding: 0;
    }

    .rich-full-panel {
      border-radius: 0;
    }
  }
  .rich-deliverable:not(.embedded) .rich-toolbar.actions-only { display: none; }
  .rich-deliverable:not(.embedded) .rich-document,
  .rich-full-body { max-width: 100rem; margin-inline: auto; padding: clamp(1rem, 3vw, 3rem); }
  .rich-body { width: 100%; margin-inline: auto; }
  .document-title { color: var(--rich-text); font-size: clamp(2rem, 4vw, 3.6rem); line-height: 1.12; letter-spacing: -.035em; overflow-wrap: anywhere; }
  .document-lede { color: var(--rich-text-secondary); max-width: 68ch; font-size: 1.2rem; line-height: 1.7; }
</style>
