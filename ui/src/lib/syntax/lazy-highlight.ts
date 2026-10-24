// Deferred syntax highlighting.
//
// Markdown and tool output render code as escaped plain text tagged with
// `data-cognis-highlight="<language>"`. A single document observer
// highlights those blocks when they come near the viewport, loading
// highlight.js on first use. This keeps highlight.js out of the startup
// bundle and avoids highlighting off-screen history on the main thread.

export const HIGHLIGHT_ATTR = 'data-cognis-highlight';
const HIGHLIGHT_SELECTOR = `[${HIGHLIGHT_ATTR}]`;
/** Very large blocks stay plain: highlighting them would block the UI. */
const MAX_HIGHLIGHT_CHARS = 100_000;
const FRAME_BUDGET_MS = 8;

/** Languages bundled in `highlight.js/lib/common` (canonical names). */
export const COMMON_HIGHLIGHT_LANGUAGES = new Set([
  'bash', 'c', 'cpp', 'csharp', 'css', 'diff', 'go', 'graphql', 'ini', 'java',
  'javascript', 'json', 'kotlin', 'less', 'lua', 'makefile', 'markdown',
  'objectivec', 'perl', 'php', 'php-template', 'plaintext', 'python',
  'python-repl', 'r', 'ruby', 'rust', 'scss', 'shell', 'sql', 'swift',
  'typescript', 'vbnet', 'wasm', 'xml', 'yaml',
]);

const ESC_MAP: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

export function escapeCodeHtml(input: string): string {
  return input.replace(/[&<>"']/g, (ch) => ESC_MAP[ch] ?? ch);
}

function safeLanguage(language: string): string {
  return language.toLowerCase().replace(/[^a-z0-9_+-]/g, '');
}

/** Escaped code wrapped in a span the observer will highlight later. */
export function deferredHighlightSpan(text: string, language: string): string {
  return `<span ${HIGHLIGHT_ATTR}="${safeLanguage(language)}">${escapeCodeHtml(text)}</span>`;
}

type Hljs = typeof import('highlight.js/lib/common').default;
let hljsPromise: Promise<Hljs> | null = null;

export function loadHighlighter(): Promise<Hljs> {
  hljsPromise ??= import('highlight.js/lib/common').then((module) => module.default);
  return hljsPromise;
}

/** Highlight one tagged element in place. Safe to call repeatedly. */
export function highlightElement(element: Element, hljs: Hljs): void {
  const language = element.getAttribute(HIGHLIGHT_ATTR) ?? '';
  element.removeAttribute(HIGHLIGHT_ATTR);
  const text = element.textContent ?? '';
  if (!language || text.length > MAX_HIGHLIGHT_CHARS || !hljs.getLanguage(language)) return;
  try {
    // hljs escapes its input, so the produced markup only contains its spans.
    element.innerHTML = hljs.highlight(text, { language, ignoreIllegals: true }).value;
    element.classList.add('hljs');
  } catch {
    // Leave the escaped plain text.
  }
}

let installed = false;

export function installLazyCodeHighlighting(root: HTMLElement = document.body): () => void {
  if (installed || typeof window === 'undefined' || typeof IntersectionObserver === 'undefined') {
    return () => undefined;
  }
  installed = true;
  const queue: Element[] = [];
  let scheduled = false;

  const drain = async () => {
    const hljs = await loadHighlighter();
    const start = performance.now();
    while (queue.length > 0 && performance.now() - start < FRAME_BUDGET_MS) {
      const element = queue.shift()!;
      if (element.isConnected && element.hasAttribute(HIGHLIGHT_ATTR)) highlightElement(element, hljs);
    }
    scheduled = false;
    if (queue.length > 0) schedule();
  };

  const schedule = () => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => void drain());
  };

  const intersection = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      intersection.unobserve(entry.target);
      queue.push(entry.target);
    }
    if (queue.length > 0) schedule();
  }, { rootMargin: '600px 0px' });

  const observeTree = (node: Node) => {
    if (!(node instanceof Element)) return;
    if (node.hasAttribute(HIGHLIGHT_ATTR)) intersection.observe(node);
    node.querySelectorAll(HIGHLIGHT_SELECTOR).forEach((element) => intersection.observe(element));
  };

  const mutations = new MutationObserver((records) => {
    for (const record of records) {
      record.addedNodes.forEach(observeTree);
    }
  });
  mutations.observe(root, { childList: true, subtree: true });
  observeTree(root);

  return () => {
    mutations.disconnect();
    intersection.disconnect();
    installed = false;
  };
}
