import { describe, expect, it, vi } from 'vitest';

import {
  DASHBOARD_MOBILE_PAGE_SIZE,
  canLoadMoreRecent,
  loadMoreRecent,
  visibleRecentItems,
} from './bounded-list';

const items = Array.from({ length: 25 }, (_, index) => index);

describe('dashboard bounded recent lists', () => {
  it('caps rows on mobile only', () => {
    expect(visibleRecentItems(items, true, DASHBOARD_MOBILE_PAGE_SIZE)).toHaveLength(10);
    expect(visibleRecentItems(items, false, DASHBOARD_MOBILE_PAGE_SIZE)).toHaveLength(25);
  });

  it('offers Load more for hidden loaded rows on mobile or more server rows', () => {
    expect(canLoadMoreRecent(25, false, true, 10)).toBe(true);
    expect(canLoadMoreRecent(10, false, true, 10)).toBe(false);
    expect(canLoadMoreRecent(25, false, false, 10)).toBe(false);
    expect(canLoadMoreRecent(5, true, false, 10)).toBe(true);
  });

  it('reveals loaded rows before fetching on mobile', () => {
    const fetchMore = vi.fn();
    expect(loadMoreRecent({ loadedCount: 25, serverHasMore: true, mobile: true, limit: 10, fetchMore })).toBe(20);
    expect(fetchMore).not.toHaveBeenCalled();
    expect(loadMoreRecent({ loadedCount: 25, serverHasMore: true, mobile: true, limit: 20, fetchMore })).toBe(30);
    expect(fetchMore).toHaveBeenCalledTimes(1);
  });

  it('fetches directly on desktop', () => {
    const fetchMore = vi.fn();
    expect(loadMoreRecent({ loadedCount: 25, serverHasMore: true, mobile: false, limit: 10, fetchMore })).toBe(10);
    expect(fetchMore).toHaveBeenCalledTimes(1);
  });
});
