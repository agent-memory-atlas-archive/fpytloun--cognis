import type { PaletteItem } from './model';

/** Small raster originals only. No controller image decoding or per-result fan-out. */
export class PaletteThumbnails {
  private cache = new Map<string, { url: string; at: number }>();
  private active = 0;
  private epoch = 0;
  private queue: { item: PaletteItem; signal: AbortSignal; resolve: (url: string) => void; epoch: number }[] = [];
  constructor(private sign: (id: string) => Promise<{ url: string }>) {}
  get(item: PaletteItem, signal: AbortSignal): Promise<string> {
    if (item.kind !== 'artifact' || !/^image\/(png|jpeg|webp|gif|avif)$/.test(item.format ?? '')
      || !item.size_bytes || item.size_bytes > 128 * 1024 || signal.aborted) return Promise.resolve('');
    const cached = this.cache.get(item.id);
    if (cached && Date.now() - cached.at < 45_000) return Promise.resolve(cached.url);
    if (this.queue.length >= 12) return Promise.resolve('');
    return new Promise((resolve) => {
      this.queue.push({ item, signal, resolve, epoch: this.epoch }); this.drain();
    });
  }
  private drain() {
    while (this.active < 2 && this.queue.length) {
      const job = this.queue.shift()!;
      if (job.signal.aborted || job.epoch !== this.epoch) { job.resolve(''); continue; }
      this.active++;
      void this.sign(job.item.id).then((result) => {
        if (job.signal.aborted || job.epoch !== this.epoch) { job.resolve(''); return; }
        this.cache.delete(job.item.id); this.cache.set(job.item.id, { url: result.url, at: Date.now() });
        while (this.cache.size > 24) this.cache.delete(this.cache.keys().next().value!);
        job.resolve(result.url);
      }, () => job.resolve('')).finally(() => { this.active--; this.drain(); });
    }
  }
  clear() {
    this.epoch++; this.cache.clear();
    for (const job of this.queue.splice(0)) job.resolve('');
  }
}
