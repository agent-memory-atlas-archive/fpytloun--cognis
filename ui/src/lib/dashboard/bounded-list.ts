// Bounded "Recent" lists for the dashboard on mobile.
//
// On desktop each dashboard column scrolls internally, so its Recent list can
// load more pages automatically when the user scrolls to its end. On mobile
// the whole page scrolls instead: auto-loading there keeps appending rows as
// the user scrolls the page, so the list never ends and the sections below it
// (for example Conversations under Tasks) become unreachable. On mobile the
// lists therefore show a fixed number of rows and grow only on an explicit
// "Load more" tap.

export const DASHBOARD_MOBILE_PAGE_SIZE = 10;
export const DASHBOARD_MOBILE_QUERY = '(max-width: 767px)';

/** Rows to render for the current layout. */
export function visibleRecentItems<T>(items: T[], mobile: boolean, limit: number): T[] {
  return mobile ? items.slice(0, limit) : items;
}

/** Whether a "Load more" control applies (more rows loaded or on the server). */
export function canLoadMoreRecent(
  loadedCount: number,
  serverHasMore: boolean,
  mobile: boolean,
  limit: number,
): boolean {
  return serverHasMore || (mobile && loadedCount > limit);
}

/**
 * Handle an explicit "Load more" tap. On mobile it reveals one more page and
 * fetches from the server only when the loaded rows would not fill it.
 * Returns the new limit.
 */
export function loadMoreRecent(options: {
  loadedCount: number;
  serverHasMore: boolean;
  mobile: boolean;
  limit: number;
  fetchMore: () => void;
}): number {
  const { loadedCount, serverHasMore, mobile, limit, fetchMore } = options;
  if (!mobile) {
    fetchMore();
    return limit;
  }
  const next = limit + DASHBOARD_MOBILE_PAGE_SIZE;
  if (loadedCount < next && serverHasMore) fetchMore();
  return next;
}
