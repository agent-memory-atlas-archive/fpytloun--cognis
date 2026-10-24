import { CoordinationUnavailableError, StaleDocumentError } from './document-coordination';
import { isConnectivityError } from './server-reachability';

export type RefreshLifecycle = {
  scope: string | null;
  eligible: boolean;
  ownerSignal?: AbortSignal;
};

export type RefreshAttempt = {
  scope: string;
  full: boolean;
  signal: AbortSignal;
};

/** Shared across sidebar and Waiting, so an ingress rejection cools both down. */
export class RefreshCooldown {
  until = 0;
}

/**
 * One flight and one latest-scope pending intent. Events cannot replenish a
 * failed retry budget or bypass a server cooldown. Explicit user retries can
 * replenish the budget, but still respect that cooldown. After three failures,
 * transient errors get one half-open attempt every 60 seconds, not a new burst.
 */
export class SidebarRefreshController {
  private flight: { scope: string; abort: AbortController } | null = null;
  private pending: { scope: string; full: boolean; urgent: boolean } | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private waiters: Array<() => void> = [];
  private disposed = false;
  private failures = 0;
  private scope: string | null = null;
  private nextRunAt = 0;
  private nextProbeAt = 0;
  private blocked = false;
  private lastSuccess: { scope: string; at: number } | null = null;
  private lifecycle: RefreshLifecycle | null = null;

  private readonly revoke = () => {
    this.pending = null;
    this.flight?.abort.abort();
    this.schedule();
    this.settle();
  };

  constructor(
    private readonly run: (attempt: RefreshAttempt) => Promise<void>,
    private readonly cooldown: RefreshCooldown,
    private readonly intervalMs = 4_000,
  ) {}

  /** Visibility/offline suspension preserves intent; a new scope/owner discards it. */
  setLifecycle(next: RefreshLifecycle): void {
    if (this.disposed) return;
    if (this.scope !== next.scope || this.lifecycle?.ownerSignal !== next.ownerSignal) {
      this.pending = null;
      this.flight?.abort.abort();
      this.settle();
      this.selectScope(next.scope);
    }
    this.lifecycle?.ownerSignal?.removeEventListener('abort', this.revoke);
    this.lifecycle = next;
    next.ownerSignal?.addEventListener('abort', this.revoke, { once: true });
    if (next.ownerSignal?.aborted || !next.scope) this.revoke();
    else this.schedule();
  }

  private selectScope(scope: string | null): void {
    this.scope = scope;
    this.lastSuccess = null;
    this.failures = 0;
    this.blocked = false;
    this.nextProbeAt = 0;
  }

  request(scope: string, options: {
    full?: boolean; urgent?: boolean; manual?: boolean; maxAgeMs?: number;
  } = {}): Promise<void> {
    if (this.disposed) return Promise.resolve();
    if (this.lifecycle && (scope !== this.lifecycle.scope || this.lifecycle.ownerSignal?.aborted)) {
      return Promise.resolve();
    }
    // Opening a surface may repair missed pushes, but must not duplicate a
    // current read or refresh a recently verified snapshot.
    if (options.maxAgeMs !== undefined && (
      (this.flight?.scope === scope && !this.flight.abort.signal.aborted)
      || (this.lastSuccess?.scope === scope && Date.now() - this.lastSuccess.at < options.maxAgeMs)
    )) return Promise.resolve();
    if (scope !== this.scope) {
      this.selectScope(scope);
    }
    if (options.manual) {
      this.failures = 0;
      this.blocked = false;
      this.nextProbeAt = 0;
    }
    if (this.blocked) return Promise.resolve();
    if (this.flight && this.flight.scope !== scope) this.flight.abort.abort();
    const previous = this.pending?.scope === scope ? this.pending : null;
    this.pending = {
      scope,
      full: Boolean(options.full || previous?.full),
      urgent: Boolean(options.urgent || previous?.urgent),
    };
    // Background recovery must not hold initial loads or event callers for minutes.
    const result = this.failures >= 3 || this.lifecycle?.eligible === false
      ? Promise.resolve()
      : new Promise<void>(resolve => this.waiters.push(resolve));
    this.schedule();
    return result;
  }

  dispose(): void {
    this.disposed = true;
    this.pending = null;
    this.flight?.abort.abort();
    this.lifecycle?.ownerSignal?.removeEventListener('abort', this.revoke);
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.settle();
  }

  private settle(): void {
    for (const resolve of this.waiters.splice(0)) resolve();
  }

  private schedule(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.disposed) return;
    if (this.blocked || this.lifecycle?.ownerSignal?.aborted) {
      this.pending = null;
      this.settle();
      return;
    }
    if (this.flight) return;
    if (!this.pending || this.lifecycle?.eligible === false) {
      this.settle();
      return;
    }
    const at = Math.max(
      this.cooldown.until,
      this.failures >= 3 ? this.nextProbeAt : 0,
      this.pending.urgent && this.failures === 0 ? 0 : this.nextRunAt,
    );
    const delay = at - Date.now();
    if (delay > 0) {
      this.timer = setTimeout(() => { this.timer = null; this.schedule(); }, delay);
      return;
    }
    void this.drain();
  }

  private async drain(): Promise<void> {
    const intent = this.pending!;
    const waiters = this.waiters.splice(0);
    this.pending = null;
    const abort = new AbortController();
    this.flight = { scope: intent.scope, abort };
    try {
      await this.run({ ...intent, signal: abort.signal });
      if (!abort.signal.aborted) {
        this.failures = 0;
        this.lastSuccess = { scope: intent.scope, at: Date.now() };
      }
    } catch (error) {
      if (!abort.signal.aborted) {
        const retryAfterMs = (error as { retryAfterMs?: number })?.retryAfterMs;
        const status = (error as { status?: number })?.status;
        const hasRetryAfter = typeof retryAfterMs === 'number'
          && Number.isFinite(retryAfterMs) && retryAfterMs >= 0;
        // Local failures use nextRunAt; only server instructions affect peers.
        if (status === 429 || hasRetryAfter) {
          this.cooldown.until = Math.max(
            this.cooldown.until,
            Date.now() + Math.max(this.intervalMs, hasRetryAfter ? retryAfterMs : 0),
          );
        }
        const revoked = error instanceof StaleDocumentError || error instanceof CoordinationUnavailableError;
        if (revoked || status === 401 || status === 403) {
          this.blocked = true;
          return;
        }
        this.failures = Math.min(3, this.failures + 1);
        const probeable = isConnectivityError(error) || status === 408 || status === 429
          || (typeof status === 'number' && status >= 500);
        if (this.failures >= 3) {
          this.nextProbeAt = Date.now() + 60_000;
          this.blocked = !probeable;
        }
        if (!this.pending) {
          this.pending = { ...intent, urgent: false };
        }
      }
    } finally {
      this.flight = null;
      this.nextRunAt = Date.now() + this.intervalMs;
      for (const resolve of waiters) resolve();
      this.schedule();
    }
  }
}

/** Keep newer pushed rows (including absence after removal) over a snapshot. */
export function overlaySidebarRows<T extends { conversation_id: string }>(
  incoming: readonly T[], current: readonly T[], protectedIds: ReadonlySet<string>,
): T[] {
  return [
    ...incoming.filter(row => !protectedIds.has(row.conversation_id)),
    ...current.filter(row => protectedIds.has(row.conversation_id)),
  ];
}

/** Apply an accepted live change to every retained scope, not just the display. */
export function updateSidebarRow<T extends { conversation_id: string }>(
  rows: readonly T[], id: string, update: (row: T) => T | null,
): T[] {
  return rows.flatMap(row => {
    const next = row.conversation_id === id ? update(row) : row;
    return next ? [next] : [];
  });
}
