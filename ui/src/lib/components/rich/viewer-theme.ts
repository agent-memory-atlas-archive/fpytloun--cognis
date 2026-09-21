import { writable } from 'svelte/store';

export type ViewerTheme = 'light' | 'dark' | 'system';
export const viewerTheme = writable<ViewerTheme>('system');
const storageKey = 'cognis-rich-viewer-theme';

export function loadViewerTheme(): void {
  try {
    const value = localStorage.getItem(storageKey);
    if (value === 'light' || value === 'dark' || value === 'system') viewerTheme.set(value);
  } catch {
    // Storage can be unavailable in private or sandboxed viewers.
  }
}

export function setViewerTheme(value: ViewerTheme): void {
  viewerTheme.set(value);
  try { localStorage.setItem(storageKey, value); } catch { /* Session preference still works. */ }
}

/** Watch only theme-bearing ancestors, including the host for embedded documents. */
export function observeViewerTheme(node: Element, changed: () => void): () => void {
  const observer = new MutationObserver(changed);
  for (let ancestor: Element | null = node; ancestor; ancestor = ancestor.parentElement) {
    observer.observe(ancestor, { attributes: true, attributeFilter: ['data-viewer-theme', 'data-resolved-theme'] });
  }
  return () => observer.disconnect();
}
