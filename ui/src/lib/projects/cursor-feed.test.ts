import { describe, expect, it, vi } from 'vitest';
import { CursorFeed } from './cursor-feed.svelte';
import type { CursorPage } from '$lib/types/api';

type Item = { id: string };
const page = (ids: string[], cursor: string | null = null): CursorPage<Item> => ({
  items: ids.map((id) => ({ id })), cursor, has_more: Boolean(cursor),
});
const settle = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

describe('CursorFeed', () => {
  it('refresh cancels an in-flight append and does not miss a newly created item', async () => {
    let resolveAppend!: (value: CursorPage<Item>) => void;
    const loader = vi.fn().mockResolvedValueOnce(page(['a'], 'tail'))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveAppend = resolve; }))
      .mockResolvedValueOnce(page(['new', 'a'], 'tail'));
    const feed = new CursorFeed<Item>((item) => item.id);
    feed.configure(loader);
    await settle();
    const append = feed.more();
    await feed.refresh();
    resolveAppend(page(['stale']));
    await append;
    expect(feed.items.map((item) => item.id)).toEqual(['new', 'a']);
    expect(loader.mock.calls[1][1].aborted).toBe(true);
  });
  it('deduplicates overlapping pages and stops repeated cursors', async () => {
    const loader = vi.fn().mockResolvedValueOnce(page(['a', 'b'], 'next'))
      .mockResolvedValueOnce(page(['b', 'c'], 'next'));
    const feed = new CursorFeed<Item>((item) => item.id);
    feed.configure(loader);
    await settle();
    await Promise.all([feed.more(), feed.more()]);
    expect(loader).toHaveBeenCalledTimes(2);
    expect(feed.items.map((item) => item.id)).toEqual(['a', 'b', 'c']);
    expect(feed.hasMore).toBe(false);
  });

  it('keeps the loaded range when refreshing after closing a modal', async () => {
    const loader = vi.fn().mockResolvedValueOnce(page(['a', 'b'], 'next'))
      .mockResolvedValueOnce(page(['c']))
      .mockResolvedValueOnce(page(['a', 'b'], 'next'))
      .mockResolvedValueOnce(page(['c']));
    const feed = new CursorFeed<Item>((item) => item.id);
    feed.configure(loader);
    await settle();
    await feed.more();
    await feed.refresh();
    expect(feed.items.map((item) => item.id)).toEqual(['a', 'b', 'c']);
    expect(loader).toHaveBeenCalledTimes(4);
  });

  it('rejects stale filter responses and preserves a failed append for retry', async () => {
    let resolveOld!: (value: CursorPage<Item>) => void;
    const feed = new CursorFeed<Item>((item) => item.id);
    feed.configure(() => new Promise((resolve) => { resolveOld = resolve; }));
    const loader = vi.fn().mockResolvedValueOnce(page(['new'], 'tail'))
      .mockRejectedValueOnce(new Error('Unavailable'))
      .mockResolvedValueOnce(page(['last']));
    feed.configure(loader);
    await settle();
    resolveOld(page(['old']));
    await settle();
    await feed.more();
    expect(feed.items).toEqual([{ id: 'new' }]);
    expect(feed.error).toBe('Unavailable');
    expect(feed.cursor).toBe('tail');
    await feed.more();
    expect(feed.items.map((item) => item.id)).toEqual(['new', 'last']);
    expect(feed.error).toBeNull();
  });
});
