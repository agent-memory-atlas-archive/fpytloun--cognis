import type { CursorPage } from '$lib/types/api';

type Loader<T> = (cursor: string | null, signal: AbortSignal) => Promise<CursorPage<T>>;

/** Owns one filtered feed; late pages from replaced filters can never publish. */
export class CursorFeed<T> {
  items = $state<T[]>([]);
  loading = $state(false);
  error = $state<string | null>(null);
  cursor = $state<string | null>(null);
  hasMore = $state(false);
  private controller: AbortController | null = null;
  private loader: Loader<T> | null = null;

  constructor(private id: (item: T) => string) {}

  configure(loader: Loader<T>): void {
    this.dispose();
    this.loader = loader;
    this.items = [];
    this.cursor = null;
    this.hasMore = false;
    void this.refresh();
  }

  dispose(): void {
    this.controller?.abort();
    this.controller = null;
    this.loading = false;
  }

  async refresh(): Promise<void> {
    if (!this.loader) return;
    this.dispose();
    await this.fetch(false);
  }

  async more(): Promise<void> {
    if (this.loading || !this.hasMore || !this.cursor) return;
    await this.fetch(true);
  }

  private async fetch(append: boolean): Promise<void> {
    const loader = this.loader;
    if (!loader) return;
    const controller = new AbortController();
    this.controller = controller;
    this.loading = true;
    this.error = null;
    const targetCount = append ? 0 : this.items.length;
    let cursor = append ? this.cursor : null;
    const items = new Map((append ? this.items : []).map((item) => [this.id(item), item]));
    const seen = new Set<string>();
    try {
      // Refresh the loaded range rather than discarding its tail on modal close.
      do {
        if (cursor) seen.add(cursor);
        const page = await loader(cursor, controller.signal);
        if (controller.signal.aborted) return;
        for (const item of page.items) items.set(this.id(item), item);
        cursor = page.has_more && page.cursor && !seen.has(page.cursor) ? page.cursor : null;
      } while (!append && cursor && items.size < targetCount);
      this.items = [...items.values()];
      this.cursor = cursor;
      this.hasMore = Boolean(cursor);
    } catch (error) {
      if (!controller.signal.aborted) this.error = error instanceof Error ? error.message : 'Could not load items';
    } finally {
      if (this.controller === controller) this.loading = false;
    }
  }
}
