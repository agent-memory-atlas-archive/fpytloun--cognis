import { get } from 'svelte/store';
import { overlayStack } from '$lib/stores/overlays';

export interface FindOptions {
  enabled?: boolean;
  primary?: boolean;
  dashboardPrimary?: boolean;
  scopeOnly?: boolean;
  identity?: () => unknown;
  open?: () => Promise<HTMLInputElement | null>;
}
interface Target { node: HTMLElement; options: FindOptions; alive: boolean }
const targets = new Set<Target>();
let workspace: (() => HTMLElement | null) | null = null;
let revision = 0;

/** Adapter to the existing workspace manager, not another window stack. */
export function registerFindWorkspace(activeRoot: () => HTMLElement | null): () => void {
  workspace = activeRoot;
  return () => { if (workspace === activeRoot) workspace = null; revision++; };
}

export function invalidateFindContext(): void { revision++; }

function visible(node: HTMLElement): boolean {
  if (!node.isConnected || node.closest('[hidden], [inert], [aria-hidden="true"]')) return false;
  if (node.matches(':disabled')) return false;
  for (let ancestor: HTMLElement | null = node; ancestor; ancestor = ancestor.parentElement) {
    const style = getComputedStyle(ancestor);
    if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') return false;
  }
  return Array.from(node.getClientRects()).some((rect) => rect.width > 0 && rect.height > 0
    && rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight);
}

function resolve(): Target | undefined {
  const overlays = get(overlayStack);
  const top = overlays.at(-1);
  const modal = top?.root?.();
  // Unmapped overlays deliberately block background search too.
  if (top && !modal) return;
  // Legacy dialogs without stack registration must never expose background targets.
  const unmappedModal = Array.from(document.querySelectorAll<HTMLElement>('dialog[open], [role="dialog"][aria-modal="true"]'))
    .some((node) => visible(node) && !overlays.some((entry) => node.contains(entry.root?.() ?? null)));
  if (unmappedModal) return;
  const activeWindow = workspace?.();
  let eligible = [...targets].filter((target) => target.alive && target.options.enabled !== false && visible(target.node));
  if (top) eligible = eligible.filter((target) => modal!.contains(target.node));
  else if (activeWindow) {
    const local = eligible.filter((target) => activeWindow.contains(target.node));
    eligible = local.length ? local : eligible.filter((target) => target.options.dashboardPrimary);
  } else {
    eligible = eligible.filter((target) => !target.node.closest('[data-find-window]'));
  }
  const focusedScope = document.activeElement?.closest('[data-find-scope]');
  const scoped = focusedScope ? eligible.filter((target) => focusedScope.contains(target.node)) : [];
  if (scoped.length === 1) return scoped[0];
  eligible = eligible.filter((target) => !target.options.scopeOnly);
  const primary = eligible.filter((target) => target.options.primary || target.options.dashboardPrimary);
  return primary.length === 1 ? primary[0] : eligible.length === 1 ? eligible[0] : undefined;
}

function select(node: HTMLInputElement): void {
  node.focus();
  if (document.activeElement === node) node.select();
}

export function findTarget(node: HTMLElement, options: FindOptions | boolean = true) {
  const normalize = (value: FindOptions | boolean): FindOptions => typeof value === 'boolean' ? { enabled: value } : value;
  const target: Target = { node, options: normalize(options), alive: true };
  targets.add(target);
  return {
    update(value: FindOptions | boolean) { target.options = normalize(value); },
    destroy() { target.alive = false; targets.delete(target); },
  };
}

export function installFind(): () => void {
  const handle = (event: KeyboardEvent): void => {
    if (event.defaultPrevented || event.isComposing || event.altKey || event.shiftKey
      || event.ctrlKey === event.metaKey || event.key.toLowerCase() !== 'f') return;
    const target = resolve();
    if (!target) return;
    if (!target.options.open) {
      if (!(target.node instanceof HTMLInputElement)) return;
      select(target.node);
      if (document.activeElement === target.node) event.preventDefault();
      return;
    }
    const version = revision;
    const identity = target.options.identity?.();
    const href = location.href;
    const overlay = get(overlayStack).at(-1);
    const activeWindow = workspace?.();
    event.preventDefault();
    void target.options.open().then((input) => {
      if (input && target.alive && version === revision && href === location.href
        && identity === target.options.identity?.() && overlay === get(overlayStack).at(-1)
        && activeWindow === workspace?.() && resolve() === target && visible(input)) select(input);
    });
  };
  window.addEventListener('keydown', handle);
  return () => { window.removeEventListener('keydown', handle); revision++; };
}
