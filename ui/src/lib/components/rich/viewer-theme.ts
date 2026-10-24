import { writable } from 'svelte/store';

export type ViewerTheme = 'light' | 'dark' | 'system' | 'app';
export const viewerTheme = writable<ViewerTheme | null>(null);
const storageKey = 'cognis-rich-viewer-theme';

export function resolveViewerTheme(
  preference: ViewerTheme | null,
  surface: 'embedded' | 'standalone',
  appTheme: string | null,
  systemDark: boolean,
): 'light' | 'dark' {
  // In-app documents belong to account appearance, never the external reader preference.
  if (surface === 'embedded'
    && (appTheme === 'light' || appTheme === 'dark')) return appTheme;
  if (surface === 'standalone' && (preference === 'light' || preference === 'dark')) return preference;
  return systemDark ? 'dark' : 'light';
}

export function loadViewerTheme(): void {
  try {
    const value = localStorage.getItem(storageKey);
    viewerTheme.set(value === 'light' || value === 'dark' || value === 'system' || value === 'app' ? value : null);
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
    observer.observe(ancestor, { attributes: true, attributeFilter: ['data-viewer-theme', 'data-resolved-theme', 'data-theme-family'] });
  }
  return () => observer.disconnect();
}
