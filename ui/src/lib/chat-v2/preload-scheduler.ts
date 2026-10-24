// Background preloading of conversation views.
//
// Conversations with activity (a running turn, a new message) are fetched in
// the background so switching to them paints the current state instantly
// instead of showing a loading/refresh state. The scheduler owns queueing,
// concurrency, per-conversation rate limits, data-saver and visibility rules,
// and cancellation; the caller supplies the actual load function.

export type PreloadPriority = 'activity' | 'idle';

export interface PreloadEnvironment {
  online(): boolean;
  visible(): boolean;
  /** True when the user asked to save data or the link is very slow. */
  constrained(): boolean;
  now(): number;
}

export const browserPreloadEnvironment: PreloadEnvironment = {
  online: () => typeof navigator === 'undefined' || navigator.onLine !== false,
  visible: () => typeof document === 'undefined' || document.visibilityState !== 'hidden',
  constrained: () => {
    const connection = typeof navigator === 'undefined'
      ? undefined
      : (navigator as Navigator & { connection?: { saveData?: boolean; effectiveType?: string } }).connection;
    if (!connection) return false;
    return connection.saveData === true || connection.effectiveType === 'slow-2g' || connection.effectiveType === '2g';
  },
  now: () => Date.now(),
};

export interface PreloadSchedulerOptions {
  concurrency?: number;
  /** Minimum time between two preloads of the same conversation. */
  minIntervalMs?: number;
  /** Minimum interval while that conversation has a running turn. */
  activeTurnIntervalMs?: number;
  maxQueued?: number;
  environment?: PreloadEnvironment;
}

type PreloadFn = (conversationId: string, signal: AbortSignal) => Promise<void>;

interface QueuedPreload {
  id: string;
  priority: PreloadPriority;
  activeTurn: boolean;
}

export class ConversationPreloadScheduler {
  private readonly queue: QueuedPreload[] = [];
  private readonly running = new Map<string, AbortController>();
  private readonly lastStarted = new Map<string, number>();
  private readonly deferred = new Map<string, ReturnType<typeof setTimeout>>();
  private readonly concurrency: number;
  private readonly minIntervalMs: number;
  private readonly activeTurnIntervalMs: number;
  private readonly maxQueued: number;
  private readonly env: PreloadEnvironment;
  private excluded: string | null = null;
  private disposed = false;

  constructor(private readonly preload: PreloadFn, options: PreloadSchedulerOptions = {}) {
    this.concurrency = options.concurrency ?? 2;
    this.minIntervalMs = options.minIntervalMs ?? 5_000;
    this.activeTurnIntervalMs = options.activeTurnIntervalMs ?? 10_000;
    this.maxQueued = options.maxQueued ?? 12;
    this.env = options.environment ?? browserPreloadEnvironment;
  }

  /** The open conversation is never preloaded; its own load path owns it. */
  setExcluded(conversationId: string | null): void {
    this.excluded = conversationId;
    if (conversationId) this.cancel(conversationId);
  }

  request(conversationId: string, options: { priority?: PreloadPriority; activeTurn?: boolean } = {}): void {
    if (this.disposed || !conversationId || conversationId === this.excluded) return;
    const priority = options.priority ?? 'activity';
    const activeTurn = options.activeTurn === true;
    if (!this.allowed(priority)) return;
    if (this.running.has(conversationId)) {
      // Re-check after the current run finishes so the latest state lands.
      this.defer(conversationId, priority, activeTurn, this.intervalFor(activeTurn));
      return;
    }
    const wait = this.waitTime(conversationId, activeTurn);
    if (wait > 0) {
      this.defer(conversationId, priority, activeTurn, wait);
      return;
    }
    const existing = this.queue.find((item) => item.id === conversationId);
    if (existing) {
      if (priority === 'activity') existing.priority = 'activity';
      existing.activeTurn ||= activeTurn;
    } else {
      if (this.queue.length >= this.maxQueued) {
        const idleIndex = this.queue.findIndex((item) => item.priority === 'idle');
        if (priority === 'idle' || idleIndex < 0) return;
        this.queue.splice(idleIndex, 1);
      }
      this.queue.push({ id: conversationId, priority, activeTurn });
    }
    this.pump();
  }

  cancel(conversationId: string): void {
    this.running.get(conversationId)?.abort();
    this.running.delete(conversationId);
    const index = this.queue.findIndex((item) => item.id === conversationId);
    if (index >= 0) this.queue.splice(index, 1);
    const timer = this.deferred.get(conversationId);
    if (timer !== undefined) clearTimeout(timer);
    this.deferred.delete(conversationId);
  }

  dispose(): void {
    this.disposed = true;
    for (const controller of this.running.values()) controller.abort();
    this.running.clear();
    this.queue.length = 0;
    for (const timer of this.deferred.values()) clearTimeout(timer);
    this.deferred.clear();
  }

  get pendingCount(): number {
    return this.queue.length + this.running.size;
  }

  private allowed(priority: PreloadPriority): boolean {
    if (!this.env.online() || !this.env.visible()) return false;
    // On data-saver / 2g only activity preloads (a running turn the user is
    // likely to open) are worth the bytes.
    if (this.env.constrained() && priority === 'idle') return false;
    return true;
  }

  private intervalFor(activeTurn: boolean): number {
    return activeTurn ? this.activeTurnIntervalMs : this.minIntervalMs;
  }

  private waitTime(conversationId: string, activeTurn: boolean): number {
    const last = this.lastStarted.get(conversationId);
    if (last === undefined) return 0;
    return Math.max(0, last + this.intervalFor(activeTurn) - this.env.now());
  }

  private defer(conversationId: string, priority: PreloadPriority, activeTurn: boolean, delayMs: number): void {
    if (this.deferred.has(conversationId)) return;
    const timer = setTimeout(() => {
      this.deferred.delete(conversationId);
      this.request(conversationId, { priority, activeTurn });
    }, Math.max(delayMs, 50));
    this.deferred.set(conversationId, timer);
  }

  private pump(): void {
    while (this.running.size < this.concurrency && this.queue.length > 0) {
      const index = this.queue.findIndex((item) => item.priority === 'activity');
      const [next] = this.queue.splice(index >= 0 ? index : 0, 1);
      if (!next || next.id === this.excluded || !this.allowed(next.priority)) continue;
      const controller = new AbortController();
      this.running.set(next.id, controller);
      this.lastStarted.set(next.id, this.env.now());
      void this.preload(next.id, controller.signal)
        .catch(() => undefined)
        .finally(() => {
          if (this.running.get(next.id) === controller) this.running.delete(next.id);
          if (!this.disposed) this.pump();
        });
    }
  }
}
