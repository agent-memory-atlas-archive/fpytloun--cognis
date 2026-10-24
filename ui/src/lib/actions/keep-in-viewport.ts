/**
 * Svelte action: keep an anchored popup (dropdown, menu, popover) inside the
 * visible viewport horizontally.
 *
 * Popups are positioned relative to their trigger (for example `right: 0`
 * under a toolbar button). When the trigger is not at the edge of a narrow
 * mobile screen, the popup can extend past the left or right edge. This
 * measures the rendered popup and shifts it back with the CSS `translate`
 * property (which composes with any existing `transform`), and caps its width
 * to the viewport. It re-measures on resize and whenever the popup changes
 * size (for example when a section expands).
 *
 * Pass a changing parameter (such as an inline style string) when the caller
 * repositions the popup itself, so the clamp is recomputed afterwards.
 */
export interface KeepInViewportOptions {
  /** Minimum distance from the viewport edges, in pixels. */
  margin?: number;
}

export function keepInViewport(
  node: HTMLElement,
  options: KeepInViewportOptions | unknown = {},
): { update(next?: KeepInViewportOptions | unknown): void; destroy(): void } {
  let margin = marginOf(options);
  let frame = 0;

  const place = () => {
    frame = 0;
    if (!node.isConnected) return;
    node.style.translate = '';
    const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
    const available = Math.max(0, viewportWidth - margin * 2);
    let rect = node.getBoundingClientRect();
    if (rect.width > available) {
      node.style.maxWidth = `${available}px`;
      rect = node.getBoundingClientRect();
    }
    let dx = 0;
    if (rect.left < margin) dx = margin - rect.left;
    else if (rect.right > viewportWidth - margin) dx = viewportWidth - margin - rect.right;
    if (dx !== 0) node.style.translate = `${Math.round(dx)}px 0`;
  };

  const schedule = () => {
    if (frame) return;
    frame = requestAnimationFrame(place);
  };

  place();
  window.addEventListener('resize', schedule);
  const resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(schedule);
  resizeObserver?.observe(node);

  return {
    update(next?: KeepInViewportOptions | unknown) {
      margin = marginOf(next);
      place();
    },
    destroy() {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener('resize', schedule);
      resizeObserver?.disconnect();
    },
  };
}

function marginOf(options: unknown): number {
  if (options && typeof options === 'object' && 'margin' in options) {
    const value = (options as KeepInViewportOptions).margin;
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return 8;
}
